require('dotenv').config();
const { Pool } = require('pg');

const pool = new Pool({
    host: process.env.DB_HOST,
    database: process.env.DB_NAME,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    port: process.env.DB_PORT,
});

const initDB = async () => {
    const schema = `
        CREATE TABLE IF NOT EXISTS employees (
            id SERIAL PRIMARY KEY,
            ad_soyad VARCHAR(255),
            departman VARCHAR(100),
            aktif SMALLINT DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS cards (
            uid VARCHAR(50) PRIMARY KEY,
            employee_id INTEGER REFERENCES employees(id),
            floors VARCHAR(100),
            valid_from BIGINT,
            valid_to BIGINT,
            aktif SMALLINT DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS devices (
            id VARCHAR(50) PRIMARY KEY,
            ad VARCHAR(100),
            kat INTEGER,
            son_gorulme BIGINT,
            durum VARCHAR(50),
            fw VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS access_events (
            id SERIAL PRIMARY KEY,
            device_id VARCHAR(50),
            seq INTEGER,
            uid VARCHAR(50),
            employee_id INTEGER,
            ts_utc BIGINT,
            ts_source SMALLINT,
            dir SMALLINT,
            result SMALLINT,
            mode SMALLINT,
            alindi_at BIGINT,
            UNIQUE(device_id, seq)
        );
    `;
    
    try {
        await pool.query(schema);
        console.log("PostgreSQL schema initialized successfully.");
    } catch (err) {
        console.error("Error initializing PostgreSQL schema:", err);
    }
};

initDB();

module.exports = pool;