require('dotenv').config();
const { Pool } = require('pg');

const pool = new Pool({
    host: process.env.DB_HOST,
    database: process.env.DB_NAME,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    port: process.env.DB_PORT,
});

// Without this, a dropped/idle connection error crashes the whole process
// (node-postgres emits 'error' on the pool for background connection
// failures - an unhandled 'error' event throws in Node).
pool.on('error', (err) => {
    console.error('Unexpected error on idle PostgreSQL client:', err.message);
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
            win_start_m SMALLINT DEFAULT 0,
            win_end_m SMALLINT DEFAULT 1440,
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

        -- CREATE TABLE IF NOT EXISTS is a no-op on tables that already exist,
        -- so anyone who ran an earlier version of this schema needs these
        -- columns added explicitly, or "win_start_m"/"win_end_m" will simply
        -- never appear and server.js's ACL query will fail.
        ALTER TABLE cards ADD COLUMN IF NOT EXISTS win_start_m SMALLINT DEFAULT 0;
        ALTER TABLE cards ADD COLUMN IF NOT EXISTS win_end_m SMALLINT DEFAULT 1440;

        -- devices.fw already existed but nothing wrote to it; these are new.
        -- Spec 7.3 requires the device status screen to show queue depth and
        -- firmware version, but the heartbeat payload's fields were being
        -- received and discarded entirely.
        ALTER TABLE devices ADD COLUMN IF NOT EXISTS queue_depth INTEGER;
        ALTER TABLE devices ADD COLUMN IF NOT EXISTS heap_free INTEGER;
        ALTER TABLE devices ADD COLUMN IF NOT EXISTS queue_overflow INTEGER;
        ALTER TABLE devices ADD COLUMN IF NOT EXISTS uptime_s BIGINT;

        -- FR-18 (OTA). One row per uploaded firmware build; the firmware's
        -- own uid-less, device-agnostic binary lives on disk under
        -- firmware_files/, this table is just the md5/size metadata needed
        -- to build the OTA command payload and verify the download.
        CREATE TABLE IF NOT EXISTS firmware (
            version VARCHAR(50) PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            md5 VARCHAR(32) NOT NULL,
            size INTEGER NOT NULL,
            uploaded_at BIGINT
        );

        -- Populated from cmd/res messages (ota_downloading / ota_ok_rebooting
        -- / ota_failed) so the panel can show update progress per device.
        ALTER TABLE devices ADD COLUMN IF NOT EXISTS ota_status VARCHAR(50);
        ALTER TABLE devices ADD COLUMN IF NOT EXISTS ota_updated_at BIGINT;

        CREATE SEQUENCE IF NOT EXISTS acl_version_seq START 1;

        CREATE SEQUENCE IF NOT EXISTS cmd_sequence START 1;
    `;

    try {
        await pool.query(schema);
        console.log('PostgreSQL schema initialized successfully.');
    } catch (err) {
        console.error('Error initializing PostgreSQL schema:', err);
        throw err;
    }
};

// Exported so callers (server.js, collector.js) can wait for the schema to
// exist before running their first query, instead of racing it.
const ready = initDB();

module.exports = pool;
module.exports.ready = ready;