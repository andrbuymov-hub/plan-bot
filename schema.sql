-- Память бота: сырая переписка + важные факты.
-- *_s — копия в нижнем регистре для поиска (LIKE в SQLite не понимает кириллицу).
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  msg_id INTEGER,
  user_id INTEGER,
  username TEXT,
  first_name TEXT,
  text TEXT,
  text_s TEXT,
  ts INTEGER NOT NULL,
  UNIQUE (chat_id, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id DESC);

CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  fact TEXT NOT NULL,
  fact_s TEXT NOT NULL,
  source TEXT,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_chat ON facts(chat_id, id DESC);
