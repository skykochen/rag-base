# API 接口文档：用户服务（User Service）
**文档版本：v2.6.0 | 基础路径：**`/api/v2/users`** | 更新日期：2024-05-01**

---

## 一、概述
用户服务提供用户账号的创建、查询、更新及权限管理能力。所有接口均采用 REST 风格，请求/响应体均为 JSON 格式。

### 1.1 认证方式
所有接口（除 `/api/v2/users/token` 外）须在 HTTP Header 中携带 Bearer Token：

```plain
Authorization: Bearer <access_token>
```

Token 通过 `/api/v2/users/token` 接口获取，有效期 **2 小时**。Token 过期后须重新获取或使用 Refresh Token 续期，Refresh Token 有效期 **20 天**。

### 1.2 通用响应格式
**成功响应（2xx）：**

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

**错误响应（4xx / 5xx）：**

```json
{
  "code": <错误码>,
  "message": "<错误描述>",
  "details": { ... }
}
```

### 1.3 限流策略
| 接口类型 | 频率上限 |
| --- | --- |
| 查询类（GET） | **200 次/分钟/用户** |
| 写入类（POST / PUT / PATCH） | **60 次/分钟/用户** |
| 删除类（DELETE） | **20 次/分钟/用户** |


超出限流阈值返回 HTTP **429 Too Many Requests**，响应头包含 `Retry-After: <秒数>`。

---

## 二、接口列表
---

### 2.1 获取访问令牌
`POST /api/v2/users/token`

**描述：** 使用用户名/密码换取访问令牌（Access Token）和刷新令牌（Refresh Token）。此接口无需鉴权。

**请求体：**

```json
{
  "username": "string",      // 用户名或邮箱
  "password": "string",      // 明文密码（TLS 传输保护）
  "mfa_code": "string"       // MFA 验证码，若账号已启用 MFA 则必填
}
```

**成功响应（200 OK）：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 7200,          // 单位：秒（2小时）
    "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
    "refresh_expires_in": 2592000 // 单位：秒（30天）
  }
}
```

**错误码：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 401 | 10001 | 用户名或密码错误 |
| 401 | 10002 | MFA 验证码错误或已过期 |
| 403 | 10003 | 账号被锁定（连续错误超 5 次） |
| 422 | 10004 | 请求体格式错误（缺少必填字段） |


---

### 2.2 创建用户
`POST /api/v2/users`

**描述：** 创建新用户账号。仅管理员（`role: admin`）可调用。

**权限：** `user:create`

**请求体：**

```json
{
  "username": "string",          // 3-64 字符，字母数字下划线，必填
  "email": "string",             // 有效邮箱地址，必填
  "password": "string",          // 需满足密码策略（见信息安全规范），必填
  "display_name": "string",      // 展示名，1-128 字符，必填
  "role": "string",              // 枚举：admin | editor | viewer，必填
  "department_id": "integer",    // 部门 ID，选填
  "phone": "string",             // E.164 格式手机号，选填
  "locale": "string"             // 语言/地区，默认 "zh-CN"
}
```

**成功响应（201 Created）：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "user_id": 10086,
    "username": "zhangsan",
    "email": "zhangsan@company.com",
    "display_name": "张三",
    "role": "editor",
    "status": "active",
    "created_at": "2024-05-01T09:00:00+08:00"
  }
}
```

**错误码：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 401 | 10001 | Token 无效或已过期 |
| 403 | 10010 | 无权创建用户（非管理员） |
| 409 | 10011 | 用户名或邮箱已被注册 |
| 422 | 10012 | 密码不满足复杂度要求 |
| 422 | 10013 | 邮箱格式无效 |


---

### 2.3 获取用户详情
`GET /api/v2/users/{user_id}`

**描述：** 获取指定用户的详细信息。普通用户只能查询自己；管理员可查询任意用户。

**权限：** `user:read`（查询他人需 `user:read:all`）

**路径参数：**

| 参数 | 类型 | 描述 |
| --- | --- | --- |
| `user_id` | integer | 用户唯一 ID |


**成功响应（200 OK）：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "user_id": 10086,
    "username": "zhangsan",
    "email": "zhangsan@company.com",
    "display_name": "张三",
    "role": "editor",
    "status": "active",
    "department_id": 42,
    "department_name": "研发部",
    "phone": "+8613800138000",
    "last_login_at": "2024-05-01T08:30:00+08:00",
    "created_at": "2024-01-15T10:00:00+08:00",
    "mfa_enabled": true
  }
}
```

**错误码：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 401 | 10001 | Token 无效或已过期 |
| 403 | 10020 | 无权查询该用户 |
| 404 | 10021 | 用户不存在 |


---

### 2.4 更新用户信息
`PATCH /api/v2/users/{user_id}`

**描述：** 更新用户的部分字段。支持局部更新（只传需要修改的字段）。管理员可更新任意用户；普通用户只能更新自己的非敏感字段（不可改 `role`、`status`）。

**权限：** `user:update`（更新他人或敏感字段需 `user:update:all`）

**请求体（所有字段均选填）：**

```json
{
  "display_name": "string",
  "phone": "string",
  "locale": "string",
  "department_id": "integer",
  "role": "string",         // 仅管理员可修改
  "status": "string"        // 枚举：active | disabled，仅管理员可修改
}
```

**成功响应（200 OK）：** 返回完整的用户对象（同 2.3）。

**错误码：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 401 | 10001 | Token 无效或已过期 |
| 403 | 10030 | 无权修改该字段 |
| 404 | 10021 | 用户不存在 |
| 422 | 10031 | 字段值非法（如 role 枚举值错误） |


---

### 2.5 修改密码
`PUT /api/v2/users/{user_id}/password`

**描述：** 修改用户密码。普通用户修改自己密码须提供旧密码；管理员重置他人密码无需旧密码，但会强制该用户下次登录时修改密码。

**请求体：**

```json
{
  "old_password": "string",   // 修改自己密码时必填；管理员重置他人时不填
  "new_password": "string"    // 必填，须满足密码策略
}
```

**成功响应（200 OK）：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "require_relogin": true   // 修改成功后当前 Token 立即失效，需重新登录
  }
}
```

**错误码：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 401 | 10040 | 旧密码错误 |
| 403 | 10041 | 无权修改他人密码 |
| 422 | 10042 | 新密码不满足复杂度要求 |
| 422 | 10043 | 新密码与最近 12 次历史密码重复 |


---

### 2.6 获取用户列表
`GET /api/v2/users`

**描述：** 分页获取用户列表。仅管理员可调用。

**权限：** `user:read:all`

**查询参数：**

| 参数 | 类型 | 默认值 | 描述 |
| --- | --- | --- | --- |
| `page` | integer | 1 | 页码，从 1 开始 |
| `page_size` | integer | 20 | 每页条数，最大 **100** |
| `role` | string | -（全部） | 过滤角色 |
| `status` | string | `active` | 过滤状态 |
| `department_id` | integer | - | 过滤部门 |
| `keyword` | string | - | 按用户名/邮箱/展示名模糊搜索 |


**成功响应（200 OK）：**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "total": 268,
    "page": 1,
    "page_size": 20,
    "items": [ /* 用户对象数组 */ ]
  }
}
```

---

### 2.7 删除用户
`DELETE /api/v2/users/{user_id}`

**描述：** 软删除用户（将状态置为 `deleted`，数据保留 **180 天**后彻底清除）。仅超级管理员（`role: super_admin`）可操作。

**权限：** `user:delete`

**成功响应（200 OK）：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "user_id": 10086,
    "deleted_at": "2024-05-01T12:00:00+08:00",
    "purge_at": "2024-10-28T12:00:00+08:00"  // 180天后彻底清除
  }
}
```

**错误码：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 403 | 10050 | 非超级管理员，无权删除 |
| 404 | 10021 | 用户不存在 |
| 409 | 10051 | 禁止删除自己 |


---

### 2.8 绑定/解绑 MFA
`POST /api/v2/users/{user_id}/mfa`

**描述：** 为用户绑定多因素认证（TOTP）。返回 TOTP 密钥和 QR 码（Base64 PNG），员工须在 Authenticator APP 中完成绑定并验证一次性密码后生效。

`DELETE /api/v2/users/{user_id}/mfa`

**描述：** 解绑 MFA，需提供当前有效 MFA 验证码。管理员解绑他人 MFA 须填写管理员自己的 MFA 验证码。

**错误码（绑定/解绑通用）：**

| HTTP 状态码 | 业务错误码 | 描述 |
| --- | --- | --- |
| 401 | 10060 | MFA 验证码无效 |
| 409 | 10061 | 该用户已绑定 MFA（重复绑定） |
| 409 | 10062 | 该用户未绑定 MFA（无法解绑） |


---

## 三、通用错误码速查表
| HTTP 状态码 | 说明 |
| --- | --- |
| 400 | 请求格式错误（Bad Request） |
| 401 | 未认证或 Token 无效/过期 |
| 403 | 已认证但权限不足（Forbidden） |
| 404 | 资源不存在（Not Found） |
| 409 | 资源冲突（Conflict），如重复注册 |
| 422 | 参数校验失败（Unprocessable Entity） |
| 429 | 请求频率超限（Too Many Requests） |
| 500 | 服务器内部错误（Internal Server Error） |
| 503 | 服务暂时不可用（Service Unavailable） |


---

## 四、SDK 示例（Python）
```python
import httpx

BASE_URL = "https://api.example.com"

# 获取 Token
resp = httpx.post(f"{BASE_URL}/api/v2/users/token", json={
    "username": "zhangsan",
    "password": "Passw0rd!",
})
token = resp.json()["data"]["access_token"]

# 查询用户详情
resp = httpx.get(
    f"{BASE_URL}/api/v2/users/10086",
    headers={"Authorization": f"Bearer {token}"}
)
print(resp.json()["data"])
```

