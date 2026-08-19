require('dotenv').config();
const express = require('express');
const mqtt = require('mqtt');
const pool = require('./db');

const app = express();
app.use(express.json());
app.use(express.static('public'));

const mqttHost = process.env.MQTT_HOST || '127.0.0.1';
const client = mqtt.connect(`mqtt://${mqttHost}:1883`);

client.on('connect', () => {
    console.log('server.js connected to Mosquitto MQTT Broker');
});

// IMPORTANT: without this handler, an unreachable broker crashes the whole
// process (Node throws on an unhandled EventEmitter 'error' event). The web
// panel/API must stay up even while the broker is down.
client.on('error', (err) => {
    console.error('MQTT connection error:', err.message);
});

// --- HELPER: normalize "1,3" / "1, 3 " / [1,3] into a clean number array ---
function parseFloors(raw) {
    if (Array.isArray(raw)) {
        return raw.map(Number).filter((n) => Number.isFinite(n));
    }
    if (typeof raw === 'string') {
        return raw
            .split(',')
            .map((s) => parseInt(s.trim(), 10))
            .filter((n) => Number.isFinite(n));
    }
    return [];
}

// Firmware expects "HH:MM-HH:MM" (exactly 11 chars); build it from the
// stored minutes-since-midnight columns.
function formatWindow(startM, endM) {
    const s = Number.isFinite(startM) ? startM : 0;
    const e = Number.isFinite(endM) ? endM : 1440;
    const pad = (n) => String(n).padStart(2, '0');
    const toHHMM = (mins) => `${pad(Math.floor(mins / 60) % 24)}:${pad(mins % 60)}`;
    return `${toHHMM(s)}-${toHHMM(e === 1440 ? 1439 : e)}`;
}

// --- HELPER FUNCTION: AUTOMATED ACL PUBLISHER ---
// Builds the JSON payload the ESP32 firmware actually needs and pushes it
// to the broker as a retained message.
const publishAclUpdate = async () => {
    try {
        // Pull everything the firmware needs to make a decision, not just uid.
        const result = await pool.query(
            'SELECT uid, floors, valid_to, win_start_m, win_end_m FROM cards WHERE aktif = 1'
        );

        const activeCards = result.rows.map((row) => ({
            uid: row.uid,
            floors: parseFloors(row.floors),
            // Firmware falls back to "no expiry" if this is missing; sending
            // it explicitly avoids relying on that fallback.
            valid_to: row.valid_to !== null ? Number(row.valid_to) : 4294967295,
            win: formatWindow(row.win_start_m, row.win_end_m),
        }));

        const newVersion = Math.floor(Date.now() / 1000);

        const aclPayload = JSON.stringify({
            ver: newVersion,
            cards: activeCards,
        });

        client.publish(
            'pdks/merkez/cfg/acl',
            aclPayload,
            { qos: 1, retain: true },
            (err) => {
                if (err) console.error('Failed to publish ACL to broker:', err);
                else console.log(`[ACL UPDATE] Version ${newVersion} published successfully.`);
            }
        );
    } catch (err) {
        console.error('Error generating ACL:', err);
    }
};

// --- API ENDPOINTS FOR THE WEB PANEL ---

// 1. GET: Live Feed of Door Scans
app.get('/api/events', async (req, res) => {
    try {
        const query = `
            SELECT a.*, e.ad_soyad, e.departman
            FROM access_events a
            LEFT JOIN cards c ON a.uid = c.uid
            LEFT JOIN employees e ON c.employee_id = e.id
            ORDER BY a.ts_utc DESC LIMIT 50
        `;
        const result = await pool.query(query);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 2. GET: Device Fleet Status
app.get('/api/devices', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM devices ORDER BY id ASC');
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 3. POST: Onboard a New Employee & Card
app.post('/api/cards/add', async (req, res) => {
    const { ad_soyad, departman, uid, floors, valid_from, valid_to, win_start_m, win_end_m } = req.body;

    if (!ad_soyad || !uid) {
        return res.status(400).json({ error: 'ad_soyad and uid are required.' });
    }

    // ESP32 always sends UID as uppercase hex with no separators - the
    // stored value must match that exactly or the card will never be found.
    const normalizedUid = String(uid).trim().toUpperCase();
    const floorsToStore = Array.isArray(floors) ? floors.join(',') : (floors || '');
    // Default to a full-day window (00:00-23:59) if the panel doesn't send one.
    const windowStart = Number.isFinite(win_start_m) ? win_start_m : 0;
    const windowEnd = Number.isFinite(win_end_m) ? win_end_m : 1440;

    // A single dedicated client is required for a real transaction - pool.query()
    // may hand BEGIN/INSERT/COMMIT to three different pooled connections,
    // making the "transaction" a no-op in practice.
    const dbClient = await pool.connect();
    try {
        await dbClient.query('BEGIN');

        const empQuery = `
            INSERT INTO employees (ad_soyad, departman)
            VALUES ($1, $2) RETURNING id
        `;
        const empResult = await dbClient.query(empQuery, [ad_soyad, departman]);
        const employeeId = empResult.rows[0].id;

        const cardQuery = `
            INSERT INTO cards (uid, employee_id, floors, valid_from, valid_to, win_start_m, win_end_m)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        `;
        await dbClient.query(cardQuery, [
            normalizedUid,
            employeeId,
            floorsToStore,
            valid_from || null,
            valid_to || null,
            windowStart,
            windowEnd,
        ]);

        await dbClient.query('COMMIT');

        // Step 3: Automatically trigger the hardware synchronization
        await publishAclUpdate();

        res.json({ message: 'Employee added and hardware updated successfully.' });
    } catch (err) {
        await dbClient.query('ROLLBACK');
        res.status(500).json({ error: 'Database transaction failed: ' + err.message });
    } finally {
        dbClient.release();
    }
});

// 4. POST: Revoke a Card (Instantly blocks access)
app.post('/api/cards/revoke', async (req, res) => {
    const { uid } = req.body;
    if (!uid) {
        return res.status(400).json({ error: 'uid is required.' });
    }
    const normalizedUid = String(uid).trim().toUpperCase();

    try {
        // Single statement - already atomic, no dedicated client needed here.
        await pool.query('UPDATE cards SET aktif = 0 WHERE uid = $1', [normalizedUid]);

        // Push the new list (which no longer includes this UID) to the hardware
        await publishAclUpdate();

        res.json({ message: 'Card revoked and hardware updated.' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Web Panel API running on http://localhost:${PORT}`);
});