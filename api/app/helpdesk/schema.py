SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    plan        TEXT NOT NULL,
    seats       INT NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id            TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    amount_cents  INT NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    status        TEXT NOT NULL,
    description   TEXT NOT NULL,
    issued_on     DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id            BIGSERIAL PRIMARY KEY,
    invoice_id    TEXT NOT NULL REFERENCES invoices(id),
    amount_cents  INT NOT NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending_approval',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tickets (
    id           BIGSERIAL PRIMARY KEY,
    customer_id  TEXT REFERENCES customers(id),
    triage       JSONB NOT NULL,
    transcript   JSONB NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
