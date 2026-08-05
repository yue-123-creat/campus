# Flask-Migrate / Alembic 使用说明

## 1) 初始化（首次）

```bash
flask db init
```

## 2) 生成迁移

```bash
flask db migrate -m "mysql cloud adapt"
```

## 3) 执行迁移

```bash
flask db upgrade
```

## 4) 回滚

```bash
flask db downgrade -1
```

> 本目录已提供一个基线版本脚本：`20260415_0001_mysql_cloud_adapt.py`。
> 生产环境请先在预发布库执行升级并验证后再上线。

