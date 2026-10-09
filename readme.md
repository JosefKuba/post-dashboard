同步邀约上线交教会
docker compose exec worker python sync.py projects

同步外语系参考
docker compose exec worker python sync.py foreign

同步帖文汇总
docker compose exec worker python sync.py summaries

同步所有数据
docker compose exec worker python sync.py all

发送昨日入库外语系参考 TOP30 到 Teams（各语系引流最高 30 条，表格，语系之间空行）
docker compose exec worker python send.py

只预览不发送
docker compose exec worker python send.py --dry-run

指定入库日期
docker compose exec worker python send.py --date 2026-08-25

跟踪同步进度（每张表一行）
docker compose logs -f --tail=50 worker

进入数据库容器
docker compose exec db psql -U post_user -d post_dashboard

修改代码之后，重新构建容器
docker compose up -d --build api web worker

