CREATE TABLE IF NOT EXISTS sessions (
    session_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    requirements JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    session_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_messages_session_id (session_id, id),
    CONSTRAINT fk_messages_session FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) ENGINE=InnoDB;
