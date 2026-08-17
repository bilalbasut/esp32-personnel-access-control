const mqtt = require('mqtt');
const pool = require('./db');

const client = mqtt.connect('mqtt://127.0.0.1:1883', {
    clientId: 'pdks-server-collector',
    clean: false
});

client.on('connect', () => {
    console.log('Collector connected to Mosquitto MQTT Broker');
    client.subscribe('pdks/merkez/dev/+/event', { qos: 1 });
    client.subscribe('pdks/merkez/dev/+/status', { qos: 1 });
});

client.on('message', async (topic, message) => {
    const payload = message.toString();
    console.log(`Received on ${topic}: ${payload}`);

    // --- Process Door Scans (Events) ---
    if (topic.endsWith('/event')) {
        const deviceId = topic.split('/')[3]; 
        let data;
        
        try {
            data = JSON.parse(payload);
        } catch (e) {
            console.error("Invalid JSON payload");
            return;
        }

        const now = Math.floor(Date.now() / 1000);
        
        // PostgreSQL parameter insertion to prevent SQL injection
        const query = `
            INSERT INTO access_events 
            (device_id, seq, uid, ts_utc, result, alindi_at) 
            VALUES ($1, $2, $3, $4, $5, $6)
        `;
        const values = [deviceId, data.seq, data.uid, data.ts, data.res, now];

        try {
            await pool.query(query, values);
            console.log(`Record saved. Sending ACK for Seq: ${data.seq}`);
            sendAck(deviceId, data.seq);
        } catch (err) {
            // PostgreSQL Error 23505 is 'unique_violation'
            if (err.code === '23505') {
                console.log(`Duplicate record ignored (Device: ${deviceId}, Seq: ${data.seq})`);
                // STILL send ACK! The ESP32 re-sent it because it missed the first ACK.
                sendAck(deviceId, data.seq);
            } else {
                console.error('Database insertion error:', err);
            }
        }
    } 
    
    // --- Process Heartbeats & Online Status ---
    else if (topic.endsWith('/status')) {
        const deviceId = topic.split('/')[3];
        const now = Math.floor(Date.now() / 1000);
        
        // PostgreSQL "UPSERT" syntax (Insert, or Update if exists)
        const query = `
            INSERT INTO devices (id, durum, son_gorulme) 
            VALUES ($1, $2, $3)
            ON CONFLICT(id) DO UPDATE SET durum = EXCLUDED.durum, son_gorulme = EXCLUDED.son_gorulme
        `;
        
        try {
            await pool.query(query, [deviceId, payload, now]);
        } catch (err) {
            console.error('Device status update error:', err);
        }
    }
});

// Sends the acknowledgment sequence back to the specific ESP32
function sendAck(deviceId, seqNumber) {
    const ackTopic = `pdks/merkez/dev/${deviceId}/event/ack`;
    const ackPayload = JSON.stringify({ ack_seq: seqNumber });
    
    client.publish(ackTopic, ackPayload, { qos: 1 }, (err) => {
        if (err) console.error('Failed to send ACK:', err);
    });
}