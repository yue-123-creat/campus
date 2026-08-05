# 蓝牙定位数据接收接口文档

## 1. 模块定位

- 平台职责：只做数据接收、校验、存储、查询。
- 硬件职责：Beacon 扫描、RSSI 处理、定位算法、坐标计算。
- 多设备支持：通过 `device_id` 区分，互不覆盖。

## 2. 接口总览

### 2.1 上传蓝牙定位（硬件调用）

- URL：`/api/ble/location/upload`
- Method：`POST`
- Content-Type：`application/json`
- 鉴权：`X-API-KEY: <你的密钥>`
- 密钥配置：环境变量 `BLE_LOCATION_API_KEY`

> 说明：若服务端未配置 `BLE_LOCATION_API_KEY`，接口默认放行，便于本地联调。生产环境请务必配置。

### 2.2 查询最新位置（前端/后台调用）

- URL：`/api/ble/location/latest?device_id=xxx`
- Method：`GET`

### 2.3 查询历史轨迹（前端/后台调用）

- URL：`/api/ble/location/history?device_id=xxx&limit=500`
- Method：`GET`
- `limit` 可选，默认 500，最大 5000

## 3. 字段规范

### 3.1 上传接口请求字段（POST Body）

| 字段 | 必传 | 类型 | 说明 | 示例 |
|---|---|---|---|---|
| `device_id` | 是 | string | 硬件唯一编号（用于区分多设备） | `esp32-s3-001` |
| `x` | 是 | number | 硬件计算后的室内坐标 X | `12.46` |
| `y` | 是 | number | 硬件计算后的室内坐标 Y | `3.18` |
| `timestamp` | 是 | string | 硬件定位时间，ISO8601 格式 | `2026-04-18T21:35:26+08:00` |

### 3.2 统一响应 JSON 结构

```json
{
  "ok": true,
  "message": "查询成功",
  "data": {}
}
```

- `ok`：布尔，是否成功
- `message`：字符串，提示信息
- `data`：对象/空对象，业务数据

## 4. 请求与响应示例

### 4.1 上传定位

请求：

```http
POST /api/ble/location/upload
Content-Type: application/json
X-API-KEY: your_ble_key
```

```json
{
  "device_id": "esp32-s3-001",
  "x": 12.46,
  "y": 3.18,
  "timestamp": "2026-04-18T21:35:26+08:00"
}
```

成功响应：

```json
{
  "ok": true,
  "message": "上传成功",
  "data": {
    "id": 101,
    "device_id": "esp32-s3-001",
    "x": 12.46,
    "y": 3.18,
    "timestamp": "2026-04-18T21:35:26+08:00"
  }
}
```

失败响应（鉴权失败）：

```json
{
  "ok": false,
  "message": "未授权：API-KEY 无效",
  "data": null
}
```

### 4.2 查询最新位置

请求：

```http
GET /api/ble/location/latest?device_id=esp32-s3-001
```

响应：

```json
{
  "ok": true,
  "message": "查询成功",
  "data": {
    "item": {
      "id": 101,
      "device_id": "esp32-s3-001",
      "x": 12.46,
      "y": 3.18,
      "timestamp": "2026-04-18T21:35:26+08:00",
      "create_time": "2026-04-18T21:35:27.125000"
    }
  }
}
```

### 4.3 查询历史轨迹

请求：

```http
GET /api/ble/location/history?device_id=esp32-s3-001&limit=100
```

响应：

```json
{
  "ok": true,
  "message": "查询成功",
  "data": {
    "device_id": "esp32-s3-001",
    "items": [
      {
        "id": 95,
        "device_id": "esp32-s3-001",
        "x": 12.10,
        "y": 3.02,
        "timestamp": "2026-04-18T21:33:26+08:00",
        "create_time": "2026-04-18T21:33:27.113000"
      },
      {
        "id": 101,
        "device_id": "esp32-s3-001",
        "x": 12.46,
        "y": 3.18,
        "timestamp": "2026-04-18T21:35:26+08:00",
        "create_time": "2026-04-18T21:35:27.125000"
      }
    ]
  }
}
```

## 5. SQLite 表结构

表名：`ble_locations`

```sql
CREATE TABLE IF NOT EXISTS ble_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    timestamp TEXT NOT NULL,
    create_time TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ble_device_time ON ble_locations(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ble_create_time ON ble_locations(create_time DESC);
```

## 6. 模块代码位置

- 蓝牙定位模块：`app/ble_location.py`
- 主程序注册入口：`app.py`
- 数据库初始化：`app/database.py`
