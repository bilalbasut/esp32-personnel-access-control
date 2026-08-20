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

// Seeded from wall-clock time so a restarted server still issues a version
// higher than whatever the device last saved (its "ver" persists in NVS
// across firmware reboots too). Bumped explicitly on every publish so two
// calls in the same second/millisecond (e.g. add then revoke back-to-back)
// can never produce an equal version - the firmware ignores non-increasing
// versions (`if (newVersion <= currentAclVersion) return;`), so a collision
// here means a real ACL change silently never reaches the device.
let lastPublishedAclVersion = Math.floor(Date.now() / 1000);

const publishAclUpdate = async () => {
    try {
        // Pull everything the firmware needs to make a decision, not just uid.
        const result = await pool.query(
            'SELECT uid, floors, valid_to, win_start_m, win_end_m FROM cards WHERE aktif = 1'
        );

        const activeCards = result.rows.map((row) => {
            const card = {
                uid: row.uid,
                floors: parseFloors(row.floors),
                // Firmware falls back to "no expiry" if this is missing; sending
                // it explicitly avoids relying on that fallback.
                valid_to: row.valid_to !== null ? Number(row.valid_to) : 4294967295,
            };

            const startM = Number.isFinite(row.win_start_m) ? row.win_start_m : 0;
            const endM = Number.isFinite(row.win_end_m) ? row.win_end_m : 1440;
            const isFullDay = startM === 0 && endM === 1440;

            // "HH:MM" can only represent up to 23:59 (minute 1439), so a full-day
            // window can never round-trip through formatWindow() without loss -
            // 1440 gets forced to 1439, and the firmware then denies access during
            // the last minute of every day (its check is `>= win_end_m`). Omitting
            // "win" entirely lets the firmware's own missing-field fallback
            // (0-1440, genuinely unrestricted) handle it correctly instead.
            if (!isFullDay) {
                card.win = formatWindow(startM, endM);
            }

            return card;
        });

        const newVersion = Math.max(Math.floor(Date.now() / 1000), lastPublishedAclVersion + 1);
        lastPublishedAclVersion = newVersion;

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

// GET: Live Feed of Door Scans
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

// GET: Device Fleet Status
app.get('/api/devices', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM devices ORDER BY id ASC');
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// GET: Employee and Card List
app.get('/api/cards', async (req, res) => {
    try {
        const query = `
            SELECT c.uid, c.floors, c.valid_from, c.valid_to, c.win_start_m, c.win_end_m, c.aktif,
                   e.id AS employee_id, e.ad_soyad, e.departman
            FROM cards c
            LEFT JOIN employees e ON c.employee_id = e.id
            ORDER BY e.ad_soyad ASC
        `;
        const result = await pool.query(query);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// GET: Date-range PDKS Report with optional CSV export
app.get('/api/reports/pdks', async (req, res) => {
    const { start_ts, end_ts, format } = req.query;
    
    if (!start_ts || !end_ts) {
        return res.status(400).json({ error: 'start_ts and end_ts (Unix timestamps) are required.' });
    }

    try {
        const query = `
            SELECT 
                e.ad_soyad, 
                e.departman,
                TO_CHAR(TO_TIMESTAMP(a.ts_utc), 'YYYY-MM-DD') as working_date,
                MIN(a.ts_utc) as first_in,
                MAX(a.ts_utc) as last_out,
                (MAX(a.ts_utc) - MIN(a.ts_utc)) as duration_seconds
            FROM access_events a
            JOIN employees e ON a.employee_id = e.id
            WHERE a.ts_utc >= $1 AND a.ts_utc <= $2 AND a.result = 0
            GROUP BY e.ad_soyad, e.departman, working_date
            ORDER BY working_date DESC, e.ad_soyad ASC
        `;
        const result = await pool.query(query, [start_ts, end_ts]);

        // Handle CSV Export
        if (format === 'csv') {
            const header = 'Name,Department,Date,First In,Last Out,Duration (Seconds)\n';
            const rows = result.rows.map(r => 
                `"${r.ad_soyad}","${r.departman}","${r.working_date}",${r.first_in},${r.last_out},${r.duration_seconds}`
            ).join('\n');
            
            res.header('Content-Type', 'text/csv');
            res.attachment('pdks_report.csv');
            return res.send(header + rows);
        }

        // Default to JSON for web panel display
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// POST: Onboard a New Employee & Card
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

    // Firmware stores floor numbers in a 32-bit bitmask and silently drops any
    // floor >= 32 (`if (floorNum < 32) ...`) - reject bad input here instead of
    // letting it fail invisibly on-device.
    const floorList = parseFloors(floors);
    if (floorList.some((f) => f < 0 || f > 31)) {
        return res.status(400).json({ error: 'floors must be between 0 and 31.' });
    }
    if (windowStart < 0 || windowStart > 1440 || windowEnd < 0 || windowEnd > 1440 || windowStart >= windowEnd) {
        return res.status(400).json({ error: 'win_start_m must be less than win_end_m, both within 0-1440.' });
    }

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
        if (err.code === '23505') {
            // uid is the PRIMARY KEY on cards - this is a duplicate card, not a
            // server fault. A previously revoked card can't be re-added through
            // this endpoint yet (that's an upsert/reactivation decision - flagging
            // rather than guessing at the policy), so surface that clearly instead
            // of a generic 500.
            res.status(409).json({ error: `Card UID ${normalizedUid} is already registered.` });
        } else {
            res.status(500).json({ error: 'Database transaction failed: ' + err.message });
        }
    } finally {
        dbClient.release();
    }
});

// POST: Revoke a Card (Instantly blocks access)
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

// POST: Send remote command to ESP32
app.post('/api/devices/:id/command', (req, res) => {
    const { id } = req.params;
    const { cmd } = req.body; 

    const validCommands = ['open', 'sync', 'reboot', 'settime', 'ota'];
    if (!validCommands.includes(cmd)) {
        return res.status(400).json({ error: 'Invalid command.' });
    }

    const cmdTopic = `pdks/merkez/dev/${id}/cmd`;
    
    client.publish(cmdTopic, cmd, { qos: 1 }, (err) => {
        if (err) {
            console.error(`Failed to send ${cmd} to ${id}:`, err);
            return res.status(500).json({ error: 'Failed to send command.' });
        }
        res.json({ message: `Command '${cmd}' queued for device ${id}.` });
    });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Web Panel API running on http://localhost:${PORT}`);
});