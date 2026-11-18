CREATE TABLE IF NOT EXISTS ops_mfa (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    totp_secret VARCHAR(64),
    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ops_mfa (id, totp_secret, mfa_enabled)
VALUES (1, NULL, FALSE)
ON CONFLICT (id) DO NOTHING;