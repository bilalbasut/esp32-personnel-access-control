const mqtt = require('mqtt');
const pool = require('./db');

const mqttHost = process.env.MQTT_HOST || '127.0.0.1';
const client = mqtt.connect(`mqtt://${mqttHost}:1883`);

// --- TRANSLATION MAPS ---
// Converts ESP32 string payloads back into SMALLINT for PostgreSQL
const mapResult = { 'granted': 0, 'unknown': 1, 'expired': 2, 'schedule': 3, 'manual': 4 };
const mapDir = { 'in': 0, 'out': 1 };
const mapMode = { 'online': 0, 'offline': 1 };
const mapTsrc = { 'ntp': 0, 'rtc': 1, 'invalid': 2 };

client.on('connect', () => {
    console.log('Collector connected to Mosquitto MQTT Broker');
    client.subscribe('pdks/merkez/dev/+/event', { qos: 1 });
    client.subscribe('pdks/merkez/dev/+/status', { qos: 1 });
    client.subscribe('pdks/merkez/dev/+/hb', { qos: 0 }); 
    client.subscribe('pdks/merkez/dev/+/cmd/res', { qos: 1 });
});

client.on('error', (err) => {
    console.error('MQTT connection error:', err.message);
});

client.on('message', async (topic, message) => {
    await pool.ready; // Wait for db.js to build tables

    const payload = message.toString();
    const topicParts = topic.split('/');
    const deviceId = topicParts[3]; 

    // --- Process Door Scans (Events) ---
    if (topic.endsWith('/event')) {
        let data;
        try {
            data = JSON.parse(payload);
        } catch (e) {
            console.error("Invalid JSON payload");
            return;
        }

        const now = Math.floor(Date.now() / 1000);

        // Opportunistic presence/firmware tracking - "fw" only ever appears on
        // event payloads, never on heartbeats, so this is the only place it can
        // be captured. Runs regardless of whether the insert below turns out to
        // be a duplicate, since it's just presence + version, not the event itself.
        try {
            await pool.query(
                `INSERT INTO devices (id, durum, son_gorulme, fw)
                 VALUES ($1, 'online', $2, $3)
                 ON CONFLICT(id) DO UPDATE SET durum = 'online', son_gorulme = EXCLUDED.son_gorulme, fw = EXCLUDED.fw`,
                [deviceId, now, data.fw || null]
            );
        } catch (err) {
            console.error('Device fw/presence update error:', err);
        }
        
        // Translate strings to integers (defaulting to safe values if undefined)
        const resInt = mapResult[data.res] ?? 1; // Default: 1 (unknown)
        const dirInt = mapDir[data.dir] ?? 0;    // Default: 0 (in)
        const modeInt = mapMode[data.mode] ?? 0; // Default: 0 (online)
        const tsrcInt = mapTsrc[data.tsrc] ?? 2; // Default: 2 (invalid)

        // Find the employee_id associated with this UID
        let employeeId = null;
        try {
            const cardLookup = await pool.query('SELECT employee_id FROM cards WHERE uid = $1', [data.uid]);
            if (cardLookup.rows.length > 0) {
                employeeId = cardLookup.rows[0].employee_id;
            }
        } catch (err) {
            console.error('Error looking up employee ID:', err);
        }
        
        // Insert all columns including dir, mode, ts_source, and employee_id
        const query = `
            INSERT INTO access_events 
            (device_id, seq, uid, employee_id, ts_utc, ts_source, dir, result, mode, alindi_at) 
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        `;
        const values = [deviceId, data.seq, data.uid, employeeId, data.ts, tsrcInt, dirInt, resInt, modeInt, now];

        try {
            await pool.query(query, values);
            console.log(`Record saved. Sending ACK for Seq: ${data.seq}`);
            sendAck(deviceId, data.seq);
        } catch (err) {
            if (err.code === '23505') {
                console.log(`Duplicate record ignored (Device: ${deviceId}, Seq: ${data.seq})`);
                sendAck(deviceId, data.seq);
            } else {
                console.error('Database insertion error:', err);
            }
        }
    } 
    
    // --- Process Online/Offline Status (LWT) ---
    else if (topic.endsWith('/status')) {
        const now = Math.floor(Date.now() / 1000);
        const query = `
            INSERT INTO devices (id, durum, son_gorulme) 
            VALUES ($1, $2, $3)
            ON CONFLICT(id) DO UPDATE SET durum = EXCLUDED.durum, son_gorulme = EXCLUDED.son_gorulme
        `;
        
        try {
            await pool.query(query, [deviceId, payload, now]);
            console.log(`Device ${deviceId} status: ${payload}`);
        } catch (err) {
            console.error('Device status update error:', err);
        }
    }

    // --- Process Heartbeats (hb) ---
    else if (topic.endsWith('/hb')) {
        const now = Math.floor(Date.now() / 1000);
        let hb = {};
        try {
            hb = JSON.parse(payload);
        } catch (e) {
            console.error('Invalid heartbeat JSON, storing presence only.');
        }

        // Upsert (not a blind UPDATE) so a heartbeat that happens to arrive
        // before this device's first /status message doesn't just silently
        // touch zero rows and lose the data.
        const query = `
            INSERT INTO devices (id, durum, son_gorulme, queue_depth, heap_free, queue_overflow, uptime_s)
            VALUES ($1, 'online', $2, $3, $4, $5, $6)
            ON CONFLICT(id) DO UPDATE SET
                durum = 'online',
                son_gorulme = EXCLUDED.son_gorulme,
                queue_depth = EXCLUDED.queue_depth,
                heap_free = EXCLUDED.heap_free,
                queue_overflow = EXCLUDED.queue_overflow,
                uptime_s = EXCLUDED.uptime_s
        `;
        try {
            await pool.query(query, [
                deviceId, now,
                hb.queue ?? null,
                hb.heap ?? null,
                hb.qOverflow ?? null,
                hb.uptime ?? null,
            ]);
        } catch (err) {
            console.error('Heartbeat update error:', err);
        }
    }

    // --- Process Command Responses ---
    else if (topic.endsWith('/cmd/res')) {
        console.log(`[CMD RESULT] Device ${deviceId} responded: ${payload}`);
    }
});

function sendAck(deviceId, seqNumber) {
    const ackTopic = `pdks/merkez/dev/${deviceId}/event/ack`;
    const ackPayload = JSON.stringify({ ack_seq: seqNumber });
    
    client.publish(ackTopic, ackPayload, { qos: 1 }, (err) => {
        if (err) console.error('Failed to send ACK:', err);
    });
}