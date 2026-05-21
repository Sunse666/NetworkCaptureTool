-- 2026-05-21 补丁：百度等站点可能产生超长上报 URL，VARCHAR(2048) 会导致 MySQL 采集入库失败。
-- 新建库请直接执行 schema.sql；已有 MySQL 库再执行本补丁。
USE network_capture_studio;

ALTER TABLE captured_requests
  MODIFY COLUMN url LONGTEXT NOT NULL,
  MODIFY COLUMN raw_curl LONGTEXT NULL,
  MODIFY COLUMN clean_curl LONGTEXT NULL;
