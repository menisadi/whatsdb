-- Usage: sqlite3 cats.db < merge.sql
-- Dedup key is (ts, sender, body). Two distinct messages with identical

ATTACH 'cats_update.db' AS upd;

INSERT INTO messages (ts, sender, body, is_system)
SELECT u.ts, u.sender, u.body, u.is_system
FROM upd.messages u
WHERE NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE STRFTIME('%Y-%m-%d %H:%M', m.ts) = STRFTIME('%Y-%m-%d %H:%M', u.ts)
      AND m.body = u.body
      AND m.sender IS u.sender
);

INSERT INTO messages_fts(messages_fts) VALUES('rebuild');

-- DETACH may report "database upd is locked"; the inserts already committed.
DETACH upd;

SELECT 'messages', COUNT(*) FROM messages;
SELECT 'messages_fts', COUNT(*) FROM messages_fts;
SELECT 'ts_min_max', MIN(ts), MAX(ts) FROM messages;
