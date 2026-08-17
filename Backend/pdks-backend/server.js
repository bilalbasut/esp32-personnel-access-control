require('dotenv').config();
const express = require('express');
const mqtt = require('mqtt');
const pool = require('./db');

const app = express();
app.use(express.json());
app.use(express.static('public'));

const mqttClient = mqtt.connect('mqtt://127.0.0.1:1883');

// --- HELPER FUNCTION: AUTOMATED ACL PUBLISHER ---
// This builds the JSON payload and pushes it to the broker
const publishAclUpdate = async () => {
    try {
        // 1. Fetch only active cards from PostgreSQL
        const result = await pool.query('SELECT uid FROM cards WHERE aktif = 1');
        const activeCards = result.rows; 
        
        // 2. The Engineering Trick: Use the Unix epoch timestamp as the version number. 
        // This guarantees the version is always larger than the ESP32's current version 
        // without needing to store a separate version counter in the database.
        const newVersion = Math.floor(Date.now() / 1000); 

        const aclPayload = JSON.stringify({
            ver: newVersion,
            cards: activeCards
        });

        // 3. Publish with QoS 1 and Retain: true
        mqttClient.publish('pdks/merkez/cfg/acl', aclPayload, { qos: 1, retain: true }, (err) => {
            if (err) console.error('Failed to publish ACL to broker:', err);
            else console.log(`[ACL UPDATE] Version ${newVersion} published successfully.`);
        });
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
    const { ad_soyad, departman, uid, floors, valid_from, valid_to } = req.body;

    try {
        // Begin a SQL Transaction (If employee insertion works but card fails, both revert)
        await pool.query('BEGIN');

        // Step 1: Create Employee and return their generated ID
        const empQuery = `
            INSERT INTO employees (ad_soyad, departman) 
            VALUES ($1, $2) RETURNING id
        `;
        const empResult = await pool.query(empQuery, [ad_soyad, departman]);
        const employeeId = empResult.rows[0].id;

        // Step 2: Assign the RFID Card to that Employee ID
        const cardQuery = `
            INSERT INTO cards (uid, employee_id, floors, valid_from, valid_to) 
            VALUES ($1, $2, $3, $4, $5)
        `;
        await pool.query(cardQuery, [uid, employeeId, floors, valid_from, valid_to]);

        await pool.query('COMMIT'); // Lock in the database changes

        // Step 3: Automatically trigger the hardware synchronization
        await publishAclUpdate();

        res.json({ message: 'Employee added and hardware updated successfully.' });
    } catch (err) {
        await pool.query('ROLLBACK'); // Cancel changes if an error occurred
        res.status(500).json({ error: 'Database transaction failed: ' + err.message });
    }
});

// 4. POST: Revoke a Card (Instantly blocks access)
app.post('/api/cards/revoke', async (req, res) => {
    const { uid } = req.body;

    try {
        // Set aktif = 0 to block the card, but keep the history
        await pool.query('UPDATE cards SET aktif = 0 WHERE uid = $1', [uid]);
        
        // Push the new list (which no longer includes this UID) to the hardware
        await publishAclUpdate();
        
        res.json({ message: 'Card revoked and hardware updated.' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

const PORT = 3000;
app.listen(PORT, () => {
    console.log(`Web Panel API running on http://localhost:${PORT}`);
});