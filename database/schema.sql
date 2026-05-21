-- 数据库初始化脚本：用于 MySQL 部署场景手动创建接口捕获软件表结构。
-- 桌面版默认使用 SQLite，启动时会由 SQLAlchemy 自动创建同等模型表。
CREATE DATABASE IF NOT EXISTS network_capture_studio
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE network_capture_studio;

-- 采集批次表：一次输入 URL 并启动采集对应一个批次。
CREATE TABLE IF NOT EXISTS capture_batches (
  id INT PRIMARY KEY AUTO_INCREMENT,
  batch_no VARCHAR(32) NOT NULL UNIQUE,
  target_url VARCHAR(2048) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'running',
  started_at DATETIME NOT NULL,
  ended_at DATETIME NULL,
  total_count INT NOT NULL DEFAULT 0,
  api_count INT NOT NULL DEFAULT 0,
  remark VARCHAR(255) NULL,
  INDEX idx_capture_batches_batch_no (batch_no),
  INDEX idx_capture_batches_started_at (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 请求记录表：保存浏览器网络请求的结构化参数、响应和 cURL。
CREATE TABLE IF NOT EXISTS captured_requests (
  id INT PRIMARY KEY AUTO_INCREMENT,
  request_id VARCHAR(128) NOT NULL,
  batch_id INT NOT NULL,
  method VARCHAR(16) NOT NULL,
  url LONGTEXT NOT NULL,
  domain VARCHAR(255) NOT NULL,
  path VARCHAR(1024) NOT NULL,
  resource_type VARCHAR(64) NOT NULL DEFAULT 'Other',
  status_code INT NULL,
  start_time DATETIME NOT NULL,
  duration_ms INT NULL,
  request_size INT NULL,
  response_size INT NULL,
  is_new BOOLEAN NOT NULL DEFAULT TRUE,
  is_api BOOLEAN NOT NULL DEFAULT TRUE,
  query_params JSON NOT NULL,
  request_headers JSON NOT NULL,
  cookies JSON NOT NULL,
  request_body JSON NULL,
  response_headers JSON NOT NULL,
  response_body JSON NULL,
  raw_curl LONGTEXT NULL,
  clean_curl LONGTEXT NULL,
  dynamic_marks JSON NOT NULL,
  INDEX idx_captured_requests_batch_id (batch_id),
  INDEX idx_captured_requests_method (method),
  INDEX idx_captured_requests_domain (domain),
  -- path 字段最长 1024，utf8mb4 全量索引会超过 MySQL 单索引长度限制，因此使用前缀索引。
  INDEX idx_captured_requests_path (path(255)),
  INDEX idx_captured_requests_status_code (status_code),
  CONSTRAINT fk_captured_requests_batch
    FOREIGN KEY (batch_id) REFERENCES capture_batches(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 用户设置表：保存背景、导出偏好、采集规则等配置。
CREATE TABLE IF NOT EXISTS user_settings (
  id INT PRIMARY KEY AUTO_INCREMENT,
  setting_key VARCHAR(128) NOT NULL UNIQUE,
  setting_value JSON NOT NULL,
  description VARCHAR(255) NULL,
  updated_at DATETIME NULL,
  INDEX idx_user_settings_key (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 操作日志表：记录用户关键操作和系统事件。
CREATE TABLE IF NOT EXISTS operation_logs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  module VARCHAR(64) NOT NULL,
  action VARCHAR(64) NOT NULL,
  result VARCHAR(32) NOT NULL,
  message TEXT NULL,
  batch_no VARCHAR(32) NULL,
  request_id VARCHAR(128) NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_operation_logs_created_at (created_at),
  INDEX idx_operation_logs_batch_no (batch_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
