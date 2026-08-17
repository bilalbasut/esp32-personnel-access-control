const express = require('express');
const mqtt = require('mqtt');
const pool = require('./db');

const app = express();
app.use(express.json());

const mqttClient = mqtt.connect('mqtt://127.0.0.1:1883');

// API: Get the 50 most recent access logs
app.get('/api/events', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM access_events ORDER BY ts_utc DESC LIMIT 50');
        res.json(result.rows); // In PostgreSQL, the actual data array is held inside 'rows'
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// API: Publish a new ACL database to the ESP32
app.post('/api/acl/update', (req, res) => {
    const newVersion = req.body.version; // Example: 38
    const cardsArray = req.body.cards;   // Array of {uid: "..."} objects

    const aclPayload = JSON.stringify({
        ver: newVersion,
        cards: cardsArray
    });

    // Publish with retain: true so offline devices get it the moment they reconnect
    mqttClient.publish('pdks/merkez/cfg/acl', aclPayload, { qos: 1, retain: true }, (err) => {
        if (err) return res.status(500).json({ error: 'Failed to publish ACL' });
        res.json({ message: `ACL Version ${newVersion} published successfully.` });
    });
});

const PORT = 3000;
app.listen(PORT, () => {
    console.log(`Web Panel API running on http://localhost:${PORT}`);
});