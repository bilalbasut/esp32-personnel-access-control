require('dotenv').config();
const express = require('express');
const cors = require('cors');
const mqtt = require('mqtt');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const pool = require('./db');

const app = express();
// Needed because the React dev server (Vite/CRA) typically runs on a
// different port than this server - without this, every relative
// fetch('/api/...') from the panel silently resolves against the frontend's
// own dev server instead of here, and just 404s there instead of ever
// reaching this code. Harmless to leave enabled in production too, since
// this API has no cookie/session auth for CORS to weaken.
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// FR-18 (OTA): where uploaded firmware binaries live on disk, and the base
// URL the device itself can reach this server at. The device can't resolve
// "localhost" - it needs the same kind of LAN-reachable address already used
// for MQTT_HOST/DB_HOST, so this follows that same env-var convention rather
// than guessing from whatever address the admin's browser happened to use.
const FIRMWARE_DIR = path.join(__dirname, 'firmware_files');
fs.mkdirSync(FIRMWARE_DIR, { recursive: true });
app.use('/firmware', express.static(FIRMWARE_DIR));

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

// Shared validation for floors + time-window fields, used by every endpoint
// that creates or fully specifies a card's access rules. Returns an error
// message string, or null if the input is valid.
function validateFloorsAndWindow(floors, windowStart, windowEnd) {
    // Firmware stores floor numbers in a 32-bit bitmask and silently drops any
    // floor >= 32 (`if (floorNum < 32) ...`) - reject bad input here instead of
    // letting it fail invisibly on-device.
    const floorList = parseFloors(floors);
    if (floorList.some((f) => f < 0 || f > 31)) {
        return 'floors must be between 0 and 31.';
    }
    if (windowStart < 0 || windowStart > 1440 || windowEnd < 0 || windowEnd > 1440 || windowStart >= windowEnd) {
        return 'win_start_m must be less than win_end_m, both within 0-1440.';
    }
    return null;
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
        const result = await pool.query(
            'SELECT uid, floors, valid_to, win_start_m, win_end_m FROM cards WHERE aktif = 1'
        );

        // Fetch strictly incrementing version number (1, 2, 3, 4...)
        const seqResult = await pool.query("SELECT nextval('acl_version_seq') AS ver");
        const newVersion = parseInt(seqResult.rows[0].ver, 10);

        const activeCards = result.rows.map((row) => {
            const card = {
                uid: row.uid,
                floors: parseFloors(row.floors),
                valid_to: row.valid_to !== null ? Number(row.valid_to) : 4294967295,
            };

            const startM = Number.isFinite(row.win_start_m) ? row.win_start_m : 0;
            const endM = Number.isFinite(row.win_end_m) ? row.win_end_m : 1440;
            if (!(startM === 0 && endM === 1440)) {
                card.win = formatWindow(startM, endM);
            }
            return card;
        });

        const aclPayload = JSON.stringify({
            ver: newVersion,
            cards: activeCards,
        });

        client.publish('pdks/merkez/cfg/acl', aclPayload, { qos: 1, retain: true });
        console.log(`[ACL UPDATE] Incremental Version ${newVersion} published.`);
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
            ORDER BY a.id DESC LIMIT 50
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

// GET: Employee list, independent of whether they have a card yet - the old
// /api/cards list starts FROM cards, so an employee with no card at all
// never appeared anywhere. This is the list a "Personnel" screen assigns
// cards from.
app.get('/api/employees', async (req, res) => {
    try {
        const query = `
            SELECT e.id, e.ad_soyad, e.departman, e.aktif, c.uid AS card_uid
            FROM employees e
            LEFT JOIN cards c ON c.employee_id = e.id
            ORDER BY e.ad_soyad ASC
        `;
        const result = await pool.query(query);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// POST: Create an employee with no card yet (e.g. a new hire before their
// card has arrived or been assigned). Use PUT /api/cards/:uid/assign
// afterward to link them to a card.
app.post('/api/employees', async (req, res) => {
    const { ad_soyad, departman } = req.body;
    if (!ad_soyad) {
        return res.status(400).json({ error: 'ad_soyad is required.' });
    }
    try {
        const result = await pool.query(
            'INSERT INTO employees (ad_soyad, departman) VALUES ($1, $2) RETURNING id, ad_soyad, departman, aktif',
            [ad_soyad, departman || null]
        );
        res.json(result.rows[0]);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// POST: Register a physical card with no owner yet (inventory/spare cards -
// cards get reissued in practice, not destroyed, so having a pool of
// unassigned cards on hand is the normal case, not an edge case). Link it to
// someone later with PUT /api/cards/:uid/assign.
//
// If employee_id is provided at creation time, the card activates
// immediately (aktif=1); if not, it's created inactive (aktif=0) so an
// unclaimed card sitting in a drawer can't open doors for whoever happens to
// be holding it. Pass aktif explicitly to override either default.
app.post('/api/cards', async (req, res) => {
    const { uid, employee_id, floors, valid_from, valid_to, win_start_m, win_end_m, aktif } = req.body;
    if (!uid) {
        return res.status(400).json({ error: 'uid is required.' });
    }

    const normalizedUid = String(uid).trim().toUpperCase();
    const windowStart = Number.isFinite(win_start_m) ? win_start_m : 0;
    const windowEnd = Number.isFinite(win_end_m) ? win_end_m : 1440;
    const normalizedEmployeeId = Number.isInteger(employee_id) ? employee_id : null;
    const cardAktif = aktif !== undefined ? (aktif ? 1 : 0) : (normalizedEmployeeId !== null ? 1 : 0);

    const validationError = validateFloorsAndWindow(floors, windowStart, windowEnd);
    if (validationError) {
        return res.status(400).json({ error: validationError });
    }

    try {
        await pool.query(
            `INSERT INTO cards (uid, employee_id, floors, valid_from, valid_to, win_start_m, win_end_m, aktif)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
            [
                normalizedUid,
                normalizedEmployeeId,
                Array.isArray(floors) ? floors.join(',') : (floors || ''),
                valid_from || null,
                valid_to || null,
                windowStart,
                windowEnd,
                cardAktif,
            ]
        );

        if (cardAktif === 1) {
            await publishAclUpdate();
        }

        res.json({ message: `Card ${normalizedUid} registered.`, aktif: cardAktif });
    } catch (err) {
        if (err.code === '23505') {
            return res.status(409).json({ error: `Card UID ${normalizedUid} is already registered.` });
        }
        if (err.code === '23503') {
            return res.status(400).json({ error: 'employee_id does not exist.' });
        }
        res.status(500).json({ error: err.message });
    }
});

// PUT: Link (or unlink) a card to/from an employee. Usable from either
// direction in the panel - the employee list ("give this person a card") or
// the card list ("assign this card to someone") - since both end up calling
// this same operation with a uid and an employee_id.
//
// employee_id has NO effect on what's sent to the device - the ACL payload
// (uid, floors, valid_to, win) never includes it, only aktif/floors/window/
// expiry do. So linking/unlinking is purely a server-side bookkeeping change
// (whose name shows up on the live feed and PDKS report for this uid), and
// does not by itself require reaching the hardware.
//
// It does, by default, flip aktif alongside the link: linking to a real
// employee activates the card, unlinking deactivates it. An active card with
// no linked owner would still physically open doors for whoever holds it,
// which is worth avoiding by default. Pass aktif explicitly to override -
// e.g. link a card to a new hire a few days early while keeping it dormant
// until their start date.
app.put('/api/cards/:uid/assign', async (req, res) => {
    const normalizedUid = String(req.params.uid).trim().toUpperCase();
    const { employee_id } = req.body;

    if (employee_id !== null && employee_id !== undefined && !Number.isInteger(employee_id)) {
        return res.status(400).json({ error: 'employee_id must be an integer, or null to unlink.' });
    }

    const newEmployeeId = employee_id ?? null;
    const aktif = 'aktif' in req.body ? (req.body.aktif ? 1 : 0) : (newEmployeeId !== null ? 1 : 0);

    try {
        const result = await pool.query(
            'UPDATE cards SET employee_id = $1, aktif = $2 WHERE uid = $3 RETURNING uid, employee_id, aktif',
            [newEmployeeId, aktif, normalizedUid]
        );
        if (result.rowCount === 0) {
            return res.status(404).json({ error: `Card UID ${normalizedUid} not found.` });
        }

        // aktif may have changed as a side effect of (un)linking, and that
        // DOES reach the device - republish either way, it's cheap and correct
        // even on the rare call where aktif didn't actually change.
        await publishAclUpdate();

        res.json({
            message: `Card ${normalizedUid} ${newEmployeeId !== null ? 'linked' : 'unlinked'}.`,
            card: result.rows[0],
        });
    } catch (err) {
        if (err.code === '23503') {
            return res.status(400).json({ error: 'employee_id does not exist.' });
        }
        res.status(500).json({ error: err.message });
    }
});

// Timezone used to bucket events into calendar days for the PDKS report.
// Records are stored in UTC (per spec 5.3); grouping by raw UTC day would
// misfile a shift that starts just after local midnight into the wrong day,
// so this must be converted explicitly rather than left to whatever
// timezone the Postgres container happens to default to (usually UTC).
const REPORT_TZ = process.env.REPORT_TZ || 'Europe/Istanbul';

// CSV field escaping: quotes the value and doubles up any embedded quotes so
// a name/department containing a comma or quote can't corrupt the row
// structure, and renders null/undefined as an empty cell instead of the
// literal string "null" (which shows up for anyone who entered but hasn't
// exited yet within the report window).
function csvField(value) {
    if (value === null || value === undefined) return '';
    return `"${String(value).replace(/"/g, '""')}"`;
}

// GET: Date-range PDKS Report with optional CSV export
app.get('/api/reports/pdks', async (req, res) => {
    const { start_ts, end_ts, format, employee_id } = req.query;
    
    if (!start_ts || !end_ts) {
        return res.status(400).json({ error: 'start_ts and end_ts (Unix timestamps) are required.' });
    }

    let employeeIdFilter = null;
    if (employee_id !== undefined && employee_id !== '') {
        employeeIdFilter = Number(employee_id);
        if (!Number.isInteger(employeeIdFilter)) {
            return res.status(400).json({ error: 'employee_id must be an integer.' });
        }
    }

    try {
        const query = `
            SELECT 
                e.id AS employee_id,
                e.ad_soyad, 
                e.departman,
                TO_CHAR(TO_TIMESTAMP(a.ts_utc) AT TIME ZONE $3, 'YYYY-MM-DD') as working_date,
                MIN(a.ts_utc) FILTER (WHERE a.dir = 0 AND a.result = 0) as first_in,
                MAX(a.ts_utc) FILTER (WHERE a.dir = 1) as last_out,
                CASE
                    WHEN MIN(a.ts_utc) FILTER (WHERE a.dir = 0 AND a.result = 0) IS NOT NULL
                     AND MAX(a.ts_utc) FILTER (WHERE a.dir = 1) IS NOT NULL
                     AND MAX(a.ts_utc) FILTER (WHERE a.dir = 1) > MIN(a.ts_utc) FILTER (WHERE a.dir = 0 AND a.result = 0)
                    THEN MAX(a.ts_utc) FILTER (WHERE a.dir = 1) - MIN(a.ts_utc) FILTER (WHERE a.dir = 0 AND a.result = 0)
                    ELSE NULL
                END as duration_seconds
            FROM access_events a
            JOIN employees e ON a.employee_id = e.id
            WHERE a.ts_utc >= $1 AND a.ts_utc <= $2
              AND ($4::int IS NULL OR a.employee_id = $4::int)
            GROUP BY e.id, e.ad_soyad, e.departman, working_date
            ORDER BY working_date DESC, e.ad_soyad ASC
        `;
        // Entries are still restricted to result=0 (granted) inside the FILTER
        // clauses above - a denied scan shouldn't count as clocking in - but
        // exits are no longer filtered by result at all, since the exit button
        // never checks the ACL and always logs result=manual, never granted.
        // The old blanket "AND a.result = 0" in the WHERE clause excluded every
        // exit row before aggregation even ran, so MAX(ts_utc) was silently
        // computed over entries only - "last exit" was really "latest entry",
        // collapsing duration to 0 whenever there was only one entry that day.
        const result = await pool.query(query, [start_ts, end_ts, REPORT_TZ, employeeIdFilter]);

        // Handle CSV Export
        if (format === 'csv') {
            const header = 'Name,Department,Date,First In,Last Out,Duration (Seconds)\n';
            const rows = result.rows.map(r => 
                [r.ad_soyad, r.departman, r.working_date, r.first_in, r.last_out, r.duration_seconds]
                    .map(csvField)
                    .join(',')
            ).join('\n');
            
            res.header('Content-Type', 'text/csv; charset=utf-8');
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
    const validationError = validateFloorsAndWindow(floors, windowStart, windowEnd);
    if (validationError) {
        return res.status(400).json({ error: validationError });
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

// DELETE: Permanently remove a card record - this is the actual "silme"
// (delete) FR-13 asks for, distinct from revoke's "aktif=0" (soft-block that
// keeps the row and its history). Deleting frees the uid entirely, e.g. to
// physically reissue the same card to a different employee - previously,
// re-adding a uid that still existed as a revoked row would hit a 409 from
// the PRIMARY KEY conflict in /api/cards/add.
// Employees are left untouched (only the cards row is removed), and past
// access_events rows aren't affected either, since they only store the raw
// uid string rather than a foreign key into cards.
app.delete('/api/cards/:uid', async (req, res) => {
    const normalizedUid = String(req.params.uid).trim().toUpperCase();

    try {
        const result = await pool.query('DELETE FROM cards WHERE uid = $1 RETURNING uid', [normalizedUid]);
        if (result.rowCount === 0) {
            return res.status(404).json({ error: `Card UID ${normalizedUid} not found.` });
        }

        // The deleted card might still have been active (aktif=1) if someone
        // deletes without revoking first - refresh the ACL so the device's
        // retained list matches reality either way.
        await publishAclUpdate();

        res.json({ message: `Card UID ${normalizedUid} deleted.` });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// POST: Send remote command to ESP32
// In-memory monotonic command sequence counter (starts from current second)
let serverCmdSeq = Math.floor(Date.now() / 1000);

app.post('/api/devices/:id/command', (req, res) => {
    const { id } = req.params;
    const { cmd, ts } = req.body; 

    const validCommands = ['open', 'sync', 'reboot', 'settime'];
    if (!validCommands.includes(cmd)) {
        return res.status(400).json({ error: 'Invalid command.' });
    }

    const now = Math.floor(Date.now() / 1000);
    const seq = ++serverCmdSeq;
    const cmdTopic = `pdks/merkez/dev/${id}/cmd`;

    // Uniform JSON envelope for all commands
    const payloadObj = {
        seq: seq,
        cmd: cmd,
        ts: now,
        params: {}
    };

    if (cmd === 'settime') {
        payloadObj.params.ts = Number.isInteger(ts) ? ts : now;
    }

    const payload = JSON.stringify(payloadObj);
    
    client.publish(cmdTopic, payload, { qos: 1 }, (err) => {
        if (err) {
            console.error(`Failed to send ${cmd} to ${id}:`, err);
            return res.status(500).json({ error: 'Failed to send command.' });
        }
        res.json({ message: `Command '${cmd}' queued for device ${id}.`, seq });
    });
});

// POST: Upload a firmware binary. Body is the raw .bin, version in the query
// string (e.g. POST /api/firmware/upload?version=1.3.0). Computes and stores
// the MD5 the firmware itself will verify against before it ever marks the
// new partition bootable - see performOTA()'s safety notes in main.cpp.
app.post(
    '/api/firmware/upload',
    express.raw({ type: 'application/octet-stream', limit: '4mb' }),
    async (req, res) => {
        const { version } = req.query;
        // The version becomes part of a filename written to disk - restrict
        // it to a safe charset so it can't be used for path traversal
        // (e.g. "../../etc/passwd").
        if (!version || !/^[a-zA-Z0-9._-]{1,50}$/.test(version)) {
            return res.status(400).json({ error: 'version query param is required (alphanumeric, dot, dash, underscore only).' });
        }
        if (!Buffer.isBuffer(req.body) || req.body.length === 0) {
            return res.status(400).json({ error: 'Request body must be the raw firmware binary (application/octet-stream).' });
        }

        const filename = `${version}.bin`;
        const md5 = crypto.createHash('md5').update(req.body).digest('hex');
        const size = req.body.length;
        const now = Math.floor(Date.now() / 1000);

        try {
            fs.writeFileSync(path.join(FIRMWARE_DIR, filename), req.body);
            await pool.query(
                `INSERT INTO firmware (version, filename, md5, size, uploaded_at)
                 VALUES ($1, $2, $3, $4, $5)
                 ON CONFLICT (version) DO UPDATE SET filename = EXCLUDED.filename, md5 = EXCLUDED.md5, size = EXCLUDED.size, uploaded_at = EXCLUDED.uploaded_at`,
                [version, filename, md5, size, now]
            );
            res.json({ message: `Firmware ${version} uploaded.`, version, md5, size });
        } catch (err) {
            res.status(500).json({ error: err.message });
        }
    }
);

// GET: List uploaded firmware versions
app.get('/api/firmware', async (req, res) => {
    try {
        const result = await pool.query('SELECT version, filename, md5, size, uploaded_at FROM firmware ORDER BY uploaded_at DESC');
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// POST: Trigger an OTA update on a specific device for a specific,
// already-uploaded firmware version. Deliberately requires an explicit
// version rather than assuming "latest" - an OTA push to a physical door
// controller shouldn't depend on an implicit ordering the caller can't see.
app.post('/api/devices/:id/ota', async (req, res) => {
    const { id } = req.params;
    const { version } = req.body;

    if (!version) {
        return res.status(400).json({ error: 'version is required.' });
    }
    const panelBaseUrl = process.env.PANEL_BASE_URL;
    if (!panelBaseUrl) {
        return res.status(500).json({ error: 'PANEL_BASE_URL is not configured - set it in .env to this server\'s LAN-reachable address (e.g. http://192.168.11.66:3000), since the device cannot resolve "localhost".' });
    }

    try {
        const result = await pool.query('SELECT filename, md5, size FROM firmware WHERE version = $1', [version]);
        if (result.rows.length === 0) {
            return res.status(404).json({ error: `Firmware version ${version} has not been uploaded.` });
        }
        const { filename, md5, size } = result.rows[0];
        const url = `${panelBaseUrl.replace(/\/$/, '')}/firmware/${filename}`;

        const cmdTopic = `pdks/merkez/dev/${id}/cmd`;
        const cmdPayload = JSON.stringify({ cmd: 'ota', url, md5, size });

        client.publish(cmdTopic, cmdPayload, { qos: 1 }, (err) => {
            if (err) {
                console.error(`Failed to send OTA command to ${id}:`, err);
                return res.status(500).json({ error: 'Failed to send OTA command.' });
            }
            res.json({ message: `OTA to version ${version} queued for device ${id}.`, url });
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Web Panel API running on http://localhost:${PORT}`);
});