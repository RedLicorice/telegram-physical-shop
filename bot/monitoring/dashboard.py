from aiohttp import web
import json
import base64
from datetime import datetime, timezone as dt_tz
from sqlalchemy import func, select, Integer

from bot.config import EnvKeys
from bot.monitoring.metrics import get_metrics
from bot.database import Database
from bot.database.models.main import (
    Order, OrderItem, ShoppingCart, Goods, Categories, BitcoinAddress, InventoryLog,
    User, Role, BotSettings, ReferenceCode, ReferenceCodeUsage,
    CryptoAddress, CustomerInfo, ReferralEarnings,
)
from bot.logger_mesh import logger


class MonitoringServer:
    """monitoring server with UI"""

    def __init__(self, host: str = None, port: int = None):
        self.host = host or EnvKeys.MONITORING_HOST
        self.port = port or EnvKeys.MONITORING_PORT
        self.app = web.Application()
        self.runner = None
        self._setup_routes()

    def _setup_routes(self):
        """Setup routes"""
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_get('/metrics', self.metrics_json)
        self.app.router.add_get('/metrics/prometheus', self.prometheus_handler)
        self.app.router.add_get('/dashboard', self.dashboard_handler)
        self.app.router.add_get('/events', self.events_handler)
        self.app.router.add_get('/performance', self.performance_handler)
        self.app.router.add_get('/errors', self.errors_handler)
        self.app.router.add_get('/business-metrics', self.business_metrics_handler)
        self.app.router.add_get('/background-tasks', self.background_tasks_handler)
        self.app.router.add_get('/products', self.products_handler)
        self.app.router.add_post('/products/add', self.products_add_handler)
        self.app.router.add_post('/products/update', self.products_update_handler)
        self.app.router.add_post('/products/delete', self.products_delete_handler)
        self.app.router.add_post('/products/stock', self.products_stock_handler)
        self.app.router.add_post('/categories/add', self.categories_add_handler)
        self.app.router.add_post('/categories/rename', self.categories_rename_handler)
        self.app.router.add_post('/categories/delete', self.categories_delete_handler)
        self.app.router.add_get('/settings', self.settings_handler)
        self.app.router.add_post('/settings/update', self.settings_update_handler)
        self.app.router.add_post('/settings/banner', self.settings_banner_handler)
        self.app.router.add_get('/users', self.users_handler)
        self.app.router.add_post('/users/role', self.users_role_handler)
        self.app.router.add_post('/users/ban', self.users_ban_handler)
        self.app.router.add_get('/refcodes', self.refcodes_handler)
        self.app.router.add_post('/refcodes/create', self.refcodes_create_handler)
        self.app.router.add_post('/refcodes/toggle', self.refcodes_toggle_handler)
        self.app.router.add_get('/wallets', self.wallets_handler)
        self.app.router.add_post('/wallets/toggle-autofeed', self.wallets_toggle_autofeed_handler)
        self.app.router.add_post('/wallets/toggle-testnet-wallets', self.wallets_toggle_testnet_handler)
        self.app.router.add_post('/wallets/currencies', self.wallets_currencies_handler)
        self.app.router.add_post('/wallets/generate', self.wallets_generate_handler)
        self.app.router.add_get('/wallets/backup/{chain}/{kind}', self.wallets_backup_handler)
        self.app.router.add_get('/export/shop', self.export_shop_handler)
        self.app.router.add_get('/export/orders', self.export_orders_handler)
        self.app.router.add_post('/import/shop', self.import_shop_handler)
        self.app.router.add_post('/import/orders', self.import_orders_handler)
        self.app.router.add_get('/', self.index_handler)

    def _get_base_html(self, title: str, content: str, active_page: str = "") -> str:
        """Generate base HTML with navigation"""
        nav_items = [
            ('/', 'Overview', 'overview'),
            ('/dashboard', 'Dashboard', 'dashboard'),
            ('/business-metrics', 'Business', 'business'),
            ('/background-tasks', 'Tasks', 'tasks'),
            ('/products', 'Products', 'products'),
            ('/users', 'Users', 'users'),
            ('/refcodes', 'Ref Codes', 'refcodes'),
            ('/settings', 'Settings', 'settings'),
            ('/wallets', 'Wallets', 'wallets'),
            ('/performance', 'Performance', 'performance'),
            ('/errors', 'Errors', 'errors'),
            ('/metrics', 'Raw JSON', 'json'),
            ('/metrics/prometheus', 'Prometheus', 'prometheus'),
        ]

        nav_html = ""
        for url, label, page_id in nav_items:
            active_class = "active" if page_id == active_page else ""
            nav_html += f'<a href="{url}" class="{active_class}">{label}</a>'

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title} - Bot Monitoring</title>
            <meta http-equiv="refresh" content="10">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #111318;
                    color: #c8ccd4;
                    min-height: 100vh;
                    padding: 0;
                }}
                a {{ color: #7b8cff; }}
                h2 {{ color: #e2e4e9; margin-bottom: 20px; font-weight: 600; }}
                h3 {{ color: #d0d3da; font-weight: 600; }}
                .container {{
                    max-width: 1280px;
                    margin: 0 auto;
                }}
                .header {{
                    background: #1a1d24;
                    border-bottom: 1px solid #2a2d35;
                    padding: 24px 32px 0;
                }}
                .header-top {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 16px;
                }}
                h1 {{
                    font-size: 1.4em;
                    font-weight: 700;
                    color: #e2e4e9;
                    letter-spacing: -0.02em;
                }}
                .header-badge {{
                    font-size: .75em;
                    padding: 4px 10px;
                    border-radius: 20px;
                    background: rgba(76,175,80,.15);
                    color: #66bb6a;
                    font-weight: 600;
                }}
                .nav {{
                    display: flex;
                    gap: 2px;
                    flex-wrap: wrap;
                }}
                .nav a {{
                    color: #7a7f8a;
                    text-decoration: none;
                    padding: 10px 16px;
                    font-size: .87em;
                    font-weight: 500;
                    border-radius: 8px 8px 0 0;
                    transition: color .2s, background .2s;
                    position: relative;
                }}
                .nav a:hover {{
                    color: #c8ccd4;
                    background: rgba(255,255,255,.04);
                }}
                .nav a.active {{
                    color: #7b8cff;
                    background: #111318;
                }}
                .nav a.active::after {{
                    content: '';
                    position: absolute;
                    bottom: 0; left: 0; right: 0;
                    height: 2px;
                    background: #7b8cff;
                    border-radius: 2px 2px 0 0;
                }}
                .content {{
                    padding: 28px 32px 40px;
                }}
                .metric-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                    gap: 16px;
                    margin-bottom: 24px;
                }}
                .metric-card {{
                    background: #1a1d24;
                    padding: 22px;
                    border-radius: 12px;
                    border: 1px solid #2a2d35;
                    transition: border-color .25s, transform .25s;
                }}
                .metric-card:hover {{
                    border-color: #3a3d48;
                    transform: translateY(-2px);
                }}
                .metric-value {{
                    font-size: 2.2em;
                    font-weight: 700;
                    color: #7b8cff;
                    margin: 8px 0 4px;
                    letter-spacing: -0.03em;
                }}
                .metric-label {{
                    color: #6b7080;
                    font-size: 0.8em;
                    text-transform: uppercase;
                    letter-spacing: 1.2px;
                    font-weight: 600;
                }}
                .chart {{
                    background: #1a1d24;
                    padding: 22px;
                    border-radius: 12px;
                    border: 1px solid #2a2d35;
                    margin-bottom: 16px;
                }}
                .chart ul {{ padding-left: 18px; }}
                .chart li {{ margin-bottom: 4px; }}
                .status-ok {{ color: #66bb6a; }}
                .status-warning {{ color: #ffa726; }}
                .status-error {{ color: #ef5350; }}
                .progress-bar {{
                    width: 100%;
                    height: 24px;
                    background: #23262e;
                    border-radius: 12px;
                    overflow: hidden;
                    margin-top: 10px;
                }}
                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, #66bb6a, #26a69a);
                    transition: width 0.5s;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: #fff;
                    font-weight: 600;
                    font-size: .85em;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 16px;
                }}
                th {{
                    background: #1e2128;
                    color: #8b90a0;
                    padding: 12px 14px;
                    text-align: left;
                    font-size: .78em;
                    text-transform: uppercase;
                    letter-spacing: .8px;
                    font-weight: 600;
                    border-bottom: 1px solid #2a2d35;
                }}
                td {{
                    padding: 11px 14px;
                    border-bottom: 1px solid #1e2128;
                    color: #b0b4be;
                }}
                tr:hover {{
                    background: rgba(123,140,255,.04);
                }}
                .footer {{
                    text-align: center;
                    padding: 18px;
                    color: #4a4e58;
                    font-size: .82em;
                    border-top: 1px solid #1e2128;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="header-top">
                        <h1>Bot Monitoring</h1>
                        <span class="header-badge">LIVE</span>
                    </div>
                    <div class="nav">{nav_html}</div>
                </div>
                <div class="content">
                    {content}
                </div>
                <div class="footer">
                    Auto-refresh 10s
                </div>
            </div>
        </body>
        </html>
        """

    async def index_handler(self, request):
        """Overview page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        uptime_hours = summary.get('uptime_seconds', 0) / 3600

        # Calculate some overview stats
        total_events = sum(summary.get('events', {}).values())
        total_errors = sum(summary.get('errors', {}).values())
        error_rate = (total_errors / total_events * 100) if total_events > 0 else 0

        # Shop stats from DB
        try:
            with Database().session() as s:
                db_users = s.query(func.count(User.telegram_id)).scalar() or 0
                db_products = s.query(func.count(Goods.name)).scalar() or 0
                db_categories = s.query(func.count(Categories.name)).scalar() or 0
                db_orders = s.query(func.count(Order.id)).scalar() or 0
                db_pending = s.query(func.count(Order.id)).filter(Order.order_status.in_(['pending', 'reserved'])).scalar() or 0
        except Exception:
            db_users = db_products = db_categories = db_orders = db_pending = 0

        content = f"""
        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-label">System Status</div>
                <div class="metric-value status-ok">ONLINE</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Uptime</div>
                <div class="metric-value">{uptime_hours:.1f}h</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Users</div>
                <div class="metric-value">{db_users}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Products</div>
                <div class="metric-value">{db_products}</div>
                <div style="color:#6b7080;font-size:.82em">{db_categories} categories</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Total Orders</div>
                <div class="metric-value">{db_orders}</div>
                <div style="color:#ffa726;font-size:.82em">{db_pending} pending</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Events / Errors</div>
                <div class="metric-value">{total_events:,}</div>
                <div style="color:{"#ef5350" if error_rate > 5 else "#6b7080"};font-size:.82em">{total_errors} errors ({error_rate:.1f}%)</div>
            </div>
        </div>
        """

        html = self._get_base_html("Overview", content, "overview")
        return web.Response(text=html, content_type='text/html')

    async def events_handler(self, request):
        """Events page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        events = summary.get('events', {})

        content = "<h2>📊 Event Statistics</h2>"
        content += '<div class="metric-grid">'

        for event, count in sorted(events.items(), key=lambda x: x[1], reverse=True):
            content += f"""
            <div class="metric-card">
                <div class="metric-label">{event.replace('_', ' ').title()}</div>
                <div class="metric-value">{count:,}</div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {min(count / max(events.values()) * 100, 100)}%">
                        {count}
                    </div>
                </div>
            </div>
            """

        content += '</div>'

        html = self._get_base_html("Events", content, "events")
        return web.Response(text=html, content_type='text/html')

    async def performance_handler(self, request):
        """Performance metrics page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        timings = summary.get('timings', {})

        content = "<h2>⚡ Performance Metrics</h2>"

        if timings:
            content += """
            <table>
                <thead>
                    <tr>
                        <th>Operation</th>
                        <th>Average (s)</th>
                        <th>Min (s)</th>
                        <th>Max (s)</th>
                        <th>Count</th>
                    </tr>
                </thead>
                <tbody>
            """

            for op, data in sorted(timings.items()):
                avg_class = 'status-ok' if data['avg'] < 1 else 'status-warning' if data['avg'] < 3 else 'status-error'
                content += f"""
                <tr>
                    <td><strong>{op.replace('_', ' ').title()}</strong></td>
                    <td class="{avg_class}">{data['avg']:.3f}</td>
                    <td>{data['min']:.3f}</td>
                    <td>{data['max']:.3f}</td>
                    <td>{data['count']}</td>
                </tr>
                """

            content += "</tbody></table>"
        else:
            content += "<p>No performance data available yet.</p>"

        html = self._get_base_html("Performance", content, "performance")
        return web.Response(text=html, content_type='text/html')

    async def errors_handler(self, request):
        """Errors page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        errors = summary.get('errors', {})

        content = "<h2>❌ Error Tracking</h2>"

        if errors:
            content += '<div class="metric-grid">'
            for error, count in sorted(errors.items(), key=lambda x: x[1], reverse=True):
                severity_class = 'status-warning' if count < 10 else 'status-error'
                content += f"""
                <div class="metric-card">
                    <div class="metric-label">{error}</div>
                    <div class="metric-value {severity_class}">{count}</div>
                </div>
                """
            content += '</div>'
        else:
            content += '<div class="metric-card"><p class="status-ok">✅ No errors detected!</p></div>'

        html = self._get_base_html("Errors", content, "errors")
        return web.Response(text=html, content_type='text/html')

    async def dashboard_handler(self, request):
        """Main dashboard"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()

        # Events summary
        events_html = ""
        if summary.get('events'):
            for event, count in list(summary['events'].items())[:5]:
                events_html += f"<li>{event}: <strong>{count}</strong></li>"

        # Errors summary
        errors_html = ""
        if summary.get('errors'):
            for error, count in summary['errors'].items():
                errors_html += f"<li class='status-error'>{error}: <strong>{count}</strong></li>"

        # Conversions
        conversions_html = ""
        if summary.get('conversions'):
            for funnel, rates in summary['conversions'].items():
                conversions_html += f"""
                <div class="metric-card">
                    <div class="metric-label">{funnel.replace('_', ' ').title()}</div>
                    {rates}
                </div>
                """

        content = f"""
        <h2>📈 Real-time Dashboard</h2>

        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-label">System Uptime</div>
                <div class="metric-value">{summary.get('uptime_seconds', 0):.0f}s</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Last Update</div>
                <div class="metric-value" style="font-size: 1em;">
                    {summary.get('timestamp', 'N/A')}
                </div>
            </div>
        </div>

        <div class="chart">
            <h3>Top Events</h3>
            <ul>{events_html or '<li>No events yet</li>'}</ul>
        </div>

        <div class="chart">
            <h3>Recent Errors</h3>
            <ul>{errors_html or '<li class="status-ok">No errors</li>'}</ul>
        </div>

        {('<div class="chart"><h3>Conversion Funnels</h3>' + conversions_html + '</div>') if conversions_html else ''}
        """

        html = self._get_base_html("Dashboard", content, "dashboard")
        return web.Response(text=html, content_type='text/html')

    async def metrics_json(self, request):
        """Return metrics as formatted JSON"""
        metrics = get_metrics()
        if not metrics:
            return web.json_response({"error": "Metrics not initialized"}, status=503)

        summary = metrics.get_metrics_summary()

        # Pretty print JSON with syntax highlighting
        json_str = json.dumps(summary, indent=2, default=str)

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Metrics JSON</title>
            <style>
                body {{
                    background: #111318; color: #c8ccd4;
                    font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace;
                    padding: 32px;
                }}
                h1 {{ color: #e2e4e9; font-size: 1.3em; margin-bottom: 16px; font-family: -apple-system, sans-serif; }}
                pre {{
                    background: #1a1d24; padding: 24px; border-radius: 10px;
                    border: 1px solid #2a2d35; overflow: auto; font-size: .9em; line-height: 1.6;
                }}
                a {{ color: #7b8cff; }}
                p {{ margin-top: 16px; }}
            </style>
        </head>
        <body>
            <h1>Raw Metrics JSON</h1>
            <pre>{json_str}</pre>
            <p><a href="/">&#8592; Back to Overview</a></p>
        </body>
        </html>
        """

        return web.Response(text=html, content_type='text/html')

    async def prometheus_handler(self, request):
        """Prometheus metrics"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="# Metrics not initialized", status=503)

        prometheus_data = metrics.export_to_prometheus()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Prometheus Metrics</title>
            <style>
                body {{
                    background: #111318; color: #c8ccd4;
                    font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace;
                    padding: 32px;
                }}
                h1 {{ color: #e2e4e9; font-size: 1.3em; margin-bottom: 16px; font-family: -apple-system, sans-serif; }}
                pre {{
                    background: #1a1d24; padding: 24px; border-radius: 10px;
                    border: 1px solid #2a2d35; overflow: auto; font-size: .9em; line-height: 1.6;
                }}
                a {{ color: #7b8cff; }}
                p {{ margin-top: 16px; }}
            </style>
        </head>
        <body>
            <h1>Prometheus Metrics</h1>
            <pre>{prometheus_data}</pre>
            <p><a href="/">&#8592; Back to Overview</a></p>
        </body>
        </html>
        """

        return web.Response(text=html, content_type='text/html')

    async def health_check(self, request):
        """Enhanced health check endpoint"""
        health_status = {
            "status": "healthy",
            "checks": {}
        }

        # Database check with connection pool info
        try:
            db = Database()
            with db.session() as s:
                # Test database connection using SQLAlchemy select
                s.scalar(select(1))

            # Get pool stats with safe attribute access
            pool = db.engine.pool
            pool_stats = {
                "size": getattr(pool, 'size', lambda: 0)(),
                "checked_in": getattr(pool, 'checkedin', lambda: 0)(),
                "checked_out": getattr(pool, 'checkedout', lambda: 0)(),
                "overflow": getattr(pool, 'overflow', lambda: 0)() if hasattr(pool, 'overflow') else 0
            }
            health_status["checks"]["database"] = {
                "status": "ok",
                "pool": pool_stats
            }

            # Check if pool is near exhaustion
            if pool_stats["checked_out"] > pool_stats["size"] * 0.9:
                health_status["checks"]["database"]["warning"] = "connection pool nearly exhausted"
                health_status["status"] = "degraded"

        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"

        # Redis/Cache check (lazy import to avoid circular dependency)
        from bot.caching.cache import get_cache_manager
        cache = get_cache_manager()
        if cache:
            try:
                # Test redis connection
                await cache.get("health_check_test")
                health_status["checks"]["redis"] = "ok"
            except Exception as e:
                health_status["checks"]["redis"] = f"error: {str(e)}"
                health_status["status"] = "degraded"
        else:
            health_status["checks"]["redis"] = "not configured"

        # Metrics system check
        metrics = get_metrics()
        if metrics:
            health_status["checks"]["metrics"] = "ok"
            health_status["uptime"] = metrics.get_metrics_summary()["uptime_seconds"]
        else:
            health_status["checks"]["metrics"] = "not initialized"
            health_status["status"] = "degraded"

        # Bitcoin address pool check - using SQLAlchemy ORM
        try:
            with Database().session() as s:
                result = s.query(func.count(BitcoinAddress.address)).filter(
                    BitcoinAddress.is_used == False
                ).scalar()

                health_status["checks"]["bitcoin_pool"] = {
                    "available": result,
                    "status": "ok" if result >= 10 else "warning" if result >= 5 else "critical"
                }

                if result < 5:
                    health_status["status"] = "degraded"

        except Exception as e:
            health_status["checks"]["bitcoin_pool"] = f"error: {str(e)}"

        # Background tasks check
        try:
            import bot.tasks.reservation_cleaner as cleaner_task
            import bot.tasks.file_watcher as watcher_task

            bg_tasks = {}

            # Check reservation cleaner
            if hasattr(cleaner_task, 'task') and cleaner_task.task:
                bg_tasks["reservation_cleaner"] = "running"
            else:
                bg_tasks["reservation_cleaner"] = "not started"

            # Check file watcher
            if hasattr(watcher_task, 'watcher') and watcher_task.watcher:
                bg_tasks["file_watcher"] = "running"
            else:
                bg_tasks["file_watcher"] = "not started"

            health_status["checks"]["background_tasks"] = bg_tasks

        except Exception as e:
            health_status["checks"]["background_tasks"] = f"error: {str(e)}"

        status_code = 200 if health_status["status"] == "healthy" else 503
        return web.json_response(health_status, status=status_code)

    async def business_metrics_handler(self, request):
        """Business metrics page - orders, inventory, payments, referrals"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        # Get analytics from metrics
        customer_journey = metrics.get_customer_journey_analytics()
        referral_analytics = metrics.get_referral_analytics()
        payment_analytics = metrics.get_payment_analytics()
        inventory_analytics = metrics.get_inventory_analytics()

        # Query database for current business state
        try:
            with Database().session() as s:
                # Orders by status - using SQLAlchemy ORM
                order_stats = s.query(
                    Order.order_status,
                    func.count().label('count')
                ).group_by(Order.order_status).all()

                # Active carts count - using SQLAlchemy ORM
                active_carts = s.query(
                    func.count(func.distinct(ShoppingCart.user_id))
                ).scalar() or 0

                # Low inventory items - using SQLAlchemy ORM with computed column
                available_stock = (Goods.stock_quantity - Goods.reserved_quantity).label('available')

                low_inventory = s.query(
                    Goods.name,
                    available_stock,
                    Goods.reserved_quantity.label('reserved')
                ).filter(
                    (Goods.stock_quantity - Goods.reserved_quantity) < 5
                ).order_by(
                    available_stock.asc()
                ).limit(10).all()

        except Exception as e:
            logger.error(f"Error fetching business metrics: {e}")
            order_stats = []
            active_carts = 0
            low_inventory = []

        # Build orders section
        orders_html = '<div class="metric-grid">'
        order_totals = {}
        for status, count in order_stats:
            order_totals[status] = count
            status_class = {
                'delivered': 'status-ok',
                'completed': 'status-ok',
                'confirmed': 'status-ok',
                'reserved': 'status-warning',
                'pending': 'status-warning',
                'cancelled': 'status-error',
                'expired': 'status-error'
            }.get(status, '')

            orders_html += f"""
            <div class="metric-card">
                <div class="metric-label">{status.title()} Orders</div>
                <div class="metric-value {status_class}">{count}</div>
            </div>
            """
        orders_html += '</div>'

        # Customer Journey section
        journey_html = f"""
        <div class="chart">
            <h3>🛒 Cart & Checkout Metrics</h3>
            <div class="metric-grid">
                <div class="metric-card">
                    <div class="metric-label">Active Carts</div>
                    <div class="metric-value">{active_carts}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Cart → Checkout Rate</div>
                    <div class="metric-value">{customer_journey['cart_metrics']['cart_to_checkout_rate']:.1f}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Abandoned Carts</div>
                    <div class="metric-value status-warning">{customer_journey['cart_metrics']['abandoned_carts']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Order Completion Rate</div>
                    <div class="metric-value">{customer_journey['order_metrics']['completion_rate']:.1f}%</div>
                </div>
            </div>
        </div>
        """

        # Payment preferences section
        payment_html = f"""
        <div class="chart">
            <h3>💳 Payment Analytics</h3>
            <div class="metric-grid">
                <div class="metric-card">
                    <div class="metric-label">Bitcoin Payments</div>
                    <div class="metric-value">{payment_analytics['payment_methods']['bitcoin']['count']}</div>
                    <small>{payment_analytics['payment_methods']['bitcoin']['percentage']:.1f}% of total</small>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Cash Payments</div>
                    <div class="metric-value">{payment_analytics['payment_methods']['cash']['count']}</div>
                    <small>{payment_analytics['payment_methods']['cash']['percentage']:.1f}% of total</small>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Bonus Usage Rate</div>
                    <div class="metric-value">{payment_analytics['bonus_usage']['bonus_usage_rate']:.1f}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Payment Completion</div>
                    <div class="metric-value">{payment_analytics['completion']['completion_rate']:.1f}%</div>
                </div>
            </div>
        </div>
        """

        # Referral program section
        referral_html = f"""
        <div class="chart">
            <h3>🎁 Referral Program</h3>
            <div class="metric-grid">
                <div class="metric-card">
                    <div class="metric-label">Codes Created</div>
                    <div class="metric-value">{referral_analytics['codes_created']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Codes Used</div>
                    <div class="metric-value">{referral_analytics['codes_used']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Usage Rate</div>
                    <div class="metric-value">{referral_analytics['usage_rate']:.1f}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Bonuses Paid</div>
                    <div class="metric-value">{referral_analytics['bonuses_paid']}</div>
                </div>
            </div>
        </div>
        """

        # Inventory section
        inventory_html = '<div class="chart"><h3>📦 Low Inventory Alert</h3>'
        if low_inventory:
            inventory_html += '<table><thead><tr><th>Item</th><th>Available</th><th>Reserved</th></tr></thead><tbody>'
            for name, available, reserved in low_inventory:
                alert_class = 'status-error' if available == 0 else 'status-warning'
                inventory_html += f"""
                <tr>
                    <td><strong>{name}</strong></td>
                    <td class="{alert_class}">{available}</td>
                    <td>{reserved}</td>
                </tr>
                """
            inventory_html += '</tbody></table>'
        else:
            inventory_html += '<p class="status-ok">✅ All items have sufficient stock</p>'
        inventory_html += '</div>'

        content = f"""
        <h2>📊 Business Metrics Dashboard</h2>

        <div class="chart">
            <h3>📋 Orders Status</h3>
            {orders_html}
        </div>

        {journey_html}
        {payment_html}
        {referral_html}
        {inventory_html}
        """

        html = self._get_base_html("Business Metrics", content, "business")
        return web.Response(text=html, content_type='text/html')

    async def background_tasks_handler(self, request):
        """Background tasks monitoring page"""
        metrics = get_metrics()
        summary = metrics.get_metrics_summary() if metrics else {}

        tasks_status = []

        # Reservation Cleaner
        try:
            # Check if any asyncio task named 'run_reservation_cleaner' is running
            import asyncio
            current_tasks = asyncio.all_tasks()
            cleaner_running = any(
                'run_reservation_cleaner' in str(task.get_coro())
                for task in current_tasks
            )

            cleaner_status = {
                "name": "Reservation Cleaner",
                "status": "running" if cleaner_running else "not started",
                "description": "Cleans up expired inventory reservations every 60 seconds",
                "metrics": {
                    "orders_expired": summary.get('events', {}).get('order_expired', 0),
                    "inventory_released": summary.get('events', {}).get('inventory_released', 0)
                }
            }
            tasks_status.append(cleaner_status)
        except Exception as e:
            tasks_status.append({
                "name": "Reservation Cleaner",
                "status": f"error: {str(e)}",
                "description": "Could not load task module"
            })

        # File Watcher
        try:
            from bot.tasks.file_watcher import get_file_watcher
            watcher_instance = get_file_watcher()
            is_running = watcher_instance.is_running() if watcher_instance else False

            watcher_status = {
                "name": "Crypto Address File Watcher",
                "status": "running" if is_running else "not started",
                "description": "Monitors address files in config/ for changes and reloads addresses",
                "metrics": {}
            }
            tasks_status.append(watcher_status)
        except Exception as e:
            tasks_status.append({
                "name": "File Watcher",
                "status": f"error: {str(e)}",
                "description": "Could not load task module"
            })

        # Payment Checker
        try:
            import asyncio
            current_tasks = asyncio.all_tasks()
            checker_running = any(
                'run_payment_checker' in str(task.get_coro())
                for task in current_tasks
            )

            tasks_status.append({
                "name": "Payment Checker",
                "status": "running" if checker_running else "not started",
                "description": "Checks block explorers for incoming crypto payments every 60 seconds",
                "metrics": {
                    "payments_detected": summary.get('events', {}).get('payment_detected', 0),
                    "payments_confirmed": summary.get('events', {}).get('payment_confirmed', 0),
                }
            })
        except Exception as e:
            tasks_status.append({
                "name": "Payment Checker",
                "status": f"error: {str(e)}",
                "description": "Could not load task module"
            })

        # Address Feeder
        try:
            current_tasks = asyncio.all_tasks()
            feeder_running = any(
                'AddressFeederTask' in str(task.get_coro()) or 'address_feeder' in str(task.get_coro())
                for task in current_tasks
            )

            tasks_status.append({
                "name": "Address Feeder",
                "status": "running" if feeder_running else "not started",
                "description": "Replenishes crypto address pools automatically every hour if auto-feed is enabled",
                "metrics": {}
            })
        except Exception as e:
            tasks_status.append({
                "name": "Address Feeder",
                "status": f"error: {str(e)}",
                "description": "Could not load task module"
            })

        # Cache Scheduler
        try:
            from bot.caching.scheduler import CacheScheduler
            cache_status = {
                "name": "Cache Scheduler",
                "status": "configured",
                "description": "Invalidates stats cache hourly, full cleanup at 3 AM daily",
                "metrics": {}
            }
            tasks_status.append(cache_status)
        except Exception as e:
            tasks_status.append({
                "name": "Cache Scheduler",
                "status": f"error: {str(e)}",
                "description": "Could not load cache scheduler"
            })

        # Build HTML
        content = '<h2>⚙️ Background Tasks Monitor</h2>'

        for task in tasks_status:
            status_class = 'status-ok' if task['status'] == 'running' or task[
                'status'] == 'configured' else 'status-error' if 'error' in task['status'] else 'status-warning'

            metrics_html = ''
            if task.get('metrics'):
                metrics_html = '<ul>'
                for key, value in task['metrics'].items():
                    metrics_html += f'<li>{key.replace("_", " ").title()}: <strong>{value}</strong></li>'
                metrics_html += '</ul>'

            content += f"""
            <div class="chart">
                <h3>{task['name']}</h3>
                <p><strong>Status:</strong> <span class="{status_class}">{task['status'].upper()}</span></p>
                <p>{task['description']}</p>
                {metrics_html}
            </div>
            """

        html = self._get_base_html("Background Tasks", content, "tasks")
        return web.Response(text=html, content_type='text/html')

    # ── Product Management ──────────────────────────────────────────

    def _products_page_css(self) -> str:
        """Extra CSS for the products management page."""
        return """
            <style>
                .pm-flash {
                    padding: 12px 20px; border-radius: 8px; margin-bottom: 20px;
                    font-weight: 500; border: 1px solid;
                }
                .pm-flash.ok  { background: rgba(102,187,106,.1); color: #66bb6a; border-color: rgba(102,187,106,.25); }
                .pm-flash.err { background: rgba(239,83,80,.1); color: #ef5350; border-color: rgba(239,83,80,.25); }
                .pm-section {
                    background: #1a1d24; padding: 24px; border-radius: 12px;
                    border: 1px solid #2a2d35; margin-bottom: 20px;
                }
                .pm-section h3 { margin-bottom: 15px; color: #d0d3da; }
                .pm-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; }
                .pm-form label { display: flex; flex-direction: column; font-size: .85em; color: #7a7f8a; }
                .pm-form input, .pm-form select, .pm-form textarea {
                    padding: 8px 12px; border: 1px solid #2e3140; border-radius: 6px;
                    font-size: .95em; margin-top: 3px;
                    background: #15171c; color: #c8ccd4;
                }
                .pm-form input:focus, .pm-form select:focus, .pm-form textarea:focus {
                    outline: none; border-color: #7b8cff;
                }
                .pm-form textarea { min-height: 60px; resize: vertical; }
                .pm-btn {
                    padding: 8px 18px; border: none; border-radius: 6px;
                    color: white; cursor: pointer; font-size: .9em; font-weight: 600;
                    transition: opacity .2s, transform .15s;
                }
                .pm-btn:hover { opacity: .85; transform: translateY(-1px); }
                .pm-btn-primary { background: #5c6bc0; }
                .pm-btn-danger  { background: #c62828; }
                .pm-btn-success { background: #2e7d32; }
                .pm-btn-warn    { background: #e65100; }
                .pm-btn-sm { padding: 5px 12px; font-size: .8em; }
                .pm-table { width: 100%; border-collapse: collapse; }
                .pm-table th {
                    background: #1e2128; color: #8b90a0; padding: 12px 10px;
                    text-align: left; font-size: .78em; text-transform: uppercase;
                    letter-spacing: .8px; font-weight: 600; border-bottom: 1px solid #2a2d35;
                }
                .pm-table td {
                    padding: 10px; border-bottom: 1px solid #1e2128;
                    vertical-align: middle; color: #b0b4be;
                }
                .pm-table tr:hover { background: rgba(123,140,255,.04); }
                .pm-actions { display: flex; gap: 6px; flex-wrap: wrap; }
                .pm-stock-avail { color: #66bb6a; font-weight: bold; }
                .pm-stock-zero  { color: #ef5350; font-weight: bold; }
                .pm-stock-reserved { color: #ffa726; font-size: .85em; }
                .pm-cats { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
                .pm-cat-badge {
                    background: rgba(123,140,255,.12); color: #9fa8da; padding: 6px 14px;
                    border-radius: 20px; font-size: .85em; font-weight: 500;
                    display: inline-flex; align-items: center; gap: 8px;
                    border: 1px solid rgba(123,140,255,.2);
                }
                details summary { cursor: pointer; font-weight: 600; color: #7b8cff; font-size: .9em; }
                details summary:hover { color: #9fa8da; }
                .pm-popup {
                    position: absolute; background: #1e2128; padding: 18px;
                    border-radius: 10px; border: 1px solid #2e3140;
                    box-shadow: 0 8px 32px rgba(0,0,0,.5);
                    z-index: 10; min-width: 320px; margin-top: 5px;
                }
                .pm-popup label {
                    display: block; margin-bottom: 8px;
                    font-size: .85em; color: #7a7f8a;
                }
                .pm-popup input, .pm-popup select, .pm-popup textarea {
                    width: 100%; padding: 7px 10px;
                    border: 1px solid #2e3140; border-radius: 5px;
                    background: #15171c; color: #c8ccd4;
                    font-size: .9em; margin-top: 3px;
                }
                .pm-popup input:focus, .pm-popup select:focus, .pm-popup textarea:focus {
                    outline: none; border-color: #7b8cff;
                }
                .pm-popup textarea { min-height: 60px; resize: vertical; }
            </style>
        """

    async def products_handler(self, request):
        """Products management page."""
        flash_msg = request.query.get('msg', '')
        flash_ok = request.query.get('ok', '1') == '1'

        try:
            with Database().session() as s:
                goods = s.query(Goods).order_by(Goods.category_name, Goods.name).all()
                categories = s.query(Categories).order_by(Categories.name).all()
                cat_names = [c.name for c in categories]

                products = []
                for g in goods:
                    products.append({
                        'name': g.name, 'price': g.price,
                        'description': g.description,
                        'category': g.category_name,
                        'stock': g.stock_quantity,
                        'reserved': g.reserved_quantity,
                        'available': g.available_quantity,
                        'image': g.image,
                    })
        except Exception as e:
            logger.error(f"Error loading products: {e}")
            products, cat_names = [], []

        # ── Flash message ──
        flash_html = ''
        if flash_msg:
            cls = 'ok' if flash_ok else 'err'
            flash_html = f'<div class="pm-flash {cls}">{flash_msg}</div>'

        # ── Categories section ──
        cats_html = '<div class="pm-section"><h3>Categories</h3>'
        cats_html += '<div class="pm-cats">'
        for c in cat_names:
            cats_html += f'<span class="pm-cat-badge">{c}</span>'
        if not cat_names:
            cats_html += '<em>No categories yet</em>'
        cats_html += '</div>'

        cats_html += '<details><summary>Manage categories</summary><div style="margin-top:15px">'
        # Add
        cats_html += '''
        <form class="pm-form" method="POST" action="/categories/add" style="margin-bottom:12px">
            <label>New category <input name="name" required></label>
            <button class="pm-btn pm-btn-primary pm-btn-sm" type="submit">Add</button>
        </form>'''
        # Rename
        cat_opts = ''.join(f'<option value="{c}">{c}</option>' for c in cat_names)
        cats_html += f'''
        <form class="pm-form" method="POST" action="/categories/rename" style="margin-bottom:12px">
            <label>Rename <select name="old_name" required>{cat_opts}</select></label>
            <label>to <input name="new_name" required></label>
            <button class="pm-btn pm-btn-warn pm-btn-sm" type="submit">Rename</button>
        </form>'''
        # Delete
        cats_html += f'''
        <form class="pm-form" method="POST" action="/categories/delete"
              onsubmit="return confirm('Delete this category and ALL its products?')">
            <label>Delete <select name="name" required>{cat_opts}</select></label>
            <button class="pm-btn pm-btn-danger pm-btn-sm" type="submit">Delete</button>
        </form>'''
        cats_html += '</div></details></div>'

        # ── Add product form ──
        add_html = '<div class="pm-section"><h3>Add Product</h3>'
        add_html += f'''
        <form class="pm-form" method="POST" action="/products/add" enctype="multipart/form-data">
            <label>Name <input name="name" required></label>
            <label>Price <input name="price" type="number" step="0.01" min="0" required></label>
            <label>Category
                <select name="category" required>{cat_opts}</select>
            </label>
            <label>Stock <input name="stock" type="number" min="0" value="0" required></label>
            <label>Image <input name="image" type="file" accept="image/*"></label>
            <label style="flex:1 1 100%">Description
                <textarea name="description" required></textarea>
            </label>
            <button class="pm-btn pm-btn-primary" type="submit">Add Product</button>
        </form>'''
        add_html += '</div>'

        # ── Products table ──
        table_html = '<div class="pm-section"><h3>Products</h3>'
        if products:
            table_html += '<table class="pm-table"><thead><tr>'
            table_html += '<th></th><th>Name</th><th>Category</th><th>Price</th><th>Stock</th><th>Description</th><th>Actions</th>'
            table_html += '</tr></thead><tbody>'

            for p in products:
                stock_cls = 'pm-stock-avail' if p['available'] > 0 else 'pm-stock-zero'
                reserved_note = f' <span class="pm-stock-reserved">({p["reserved"]} reserved)</span>' if p['reserved'] > 0 else ''
                desc_short = (p['description'][:60] + '...') if len(p['description']) > 60 else p['description']

                img_html = f'<img src="data:image/png;base64,{p["image"]}" style="width:48px;height:48px;object-fit:cover;border-radius:6px">' if p['image'] else '<span style="color:#ccc;font-size:1.5em">--</span>'
                has_img_label = 'Replace image' if p['image'] else 'Add image'

                table_html += f'''<tr>
                    <td style="width:56px;text-align:center">{img_html}</td>
                    <td><strong>{p["name"]}</strong></td>
                    <td>{p["category"]}</td>
                    <td>{p["price"]}</td>
                    <td><span class="{stock_cls}">{p["available"]}</span> / {p["stock"]}{reserved_note}</td>
                    <td title="{p["description"]}">{desc_short}</td>
                    <td class="pm-actions">
                        <details><summary class="pm-btn pm-btn-warn pm-btn-sm">Edit</summary>
                        <div class="pm-popup">
                            <form method="POST" action="/products/update" enctype="multipart/form-data">
                                <input type="hidden" name="old_name" value="{p["name"]}">
                                <label style="display:block;margin-bottom:8px">Name<br>
                                    <input name="new_name" value="{p["name"]}" style="width:100%">
                                </label>
                                <label style="display:block;margin-bottom:8px">Price<br>
                                    <input name="price" type="number" step="0.01" value="{p["price"]}" style="width:100%">
                                </label>
                                <label style="display:block;margin-bottom:8px">Category<br>
                                    <select name="category" style="width:100%">
                                        {"".join(f'<option value="{c}" {"selected" if c == p["category"] else ""}>{c}</option>' for c in cat_names)}
                                    </select>
                                </label>
                                <label style="display:block;margin-bottom:8px">{has_img_label}<br>
                                    <input name="image" type="file" accept="image/*" style="width:100%;padding:6px">
                                </label>
                                <label style="display:block;margin-bottom:8px">Description<br>
                                    <textarea name="description" style="width:100%;min-height:60px">{p["description"]}</textarea>
                                </label>
                                <button class="pm-btn pm-btn-primary pm-btn-sm" type="submit">Save</button>
                            </form>
                        </div></details>

                        <details><summary class="pm-btn pm-btn-success pm-btn-sm">Stock</summary>
                        <div class="pm-popup" style="min-width:260px">
                            <form method="POST" action="/products/stock">
                                <input type="hidden" name="item_name" value="{p["name"]}">
                                <label style="display:block;margin-bottom:8px">Quantity<br>
                                    <input name="quantity" type="number" min="1" value="1" style="width:100%">
                                </label>
                                <label style="display:block;margin-bottom:8px">Action<br>
                                    <select name="action" style="width:100%">
                                        <option value="add">Add to stock</option>
                                        <option value="set">Set exact stock</option>
                                        <option value="remove">Remove from stock</option>
                                    </select>
                                </label>
                                <button class="pm-btn pm-btn-success pm-btn-sm" type="submit">Apply</button>
                            </form>
                        </div></details>

                        <form method="POST" action="/products/delete" style="display:inline"
                              onsubmit="return confirm('Delete {p["name"]}?')">
                            <input type="hidden" name="name" value="{p["name"]}">
                            <button class="pm-btn pm-btn-danger pm-btn-sm" type="submit">Delete</button>
                        </form>
                    </td>
                </tr>'''

            table_html += '</tbody></table>'
        else:
            table_html += '<p>No products yet. Add a category first, then add products.</p>'
        table_html += '</div>'

        content = self._products_page_css() + flash_html + cats_html + add_html + table_html
        html = self._get_base_html("Products", content, "products")
        # Disable auto-refresh on management page
        html = html.replace('<meta http-equiv="refresh" content="10">', '')
        return web.Response(text=html, content_type='text/html')

    @staticmethod
    def _redirect_products(msg: str = '', ok: bool = True):
        """Return a 302 redirect back to the products page."""
        from urllib.parse import quote
        url = f'/products?msg={quote(msg)}&ok={"1" if ok else "0"}' if msg else '/products'
        return web.HTTPFound(url)

    @staticmethod
    @staticmethod
    async def _read_upload_image(data, max_size: int = 800) -> str | None:
        """Read an uploaded image, resize if larger than max_size px, return base64."""
        from io import BytesIO
        from PIL import Image

        image_field = data.get('image')
        if not image_field or not hasattr(image_field, 'file') or not image_field.filename:
            return None
        raw = image_field.file.read()
        if not raw:
            return None

        img = Image.open(BytesIO(raw))
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)

        buf = BytesIO()
        fmt = 'PNG' if img.mode == 'RGBA' else 'JPEG'
        img.save(buf, format=fmt, quality=85, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('ascii')

    async def products_add_handler(self, request):
        """POST: add a new product."""
        data = await request.post()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        price_str = data.get('price', '0')
        category = data.get('category', '').strip()
        stock_str = data.get('stock', '0')

        if not name or not description or not category:
            raise self._redirect_products('All fields are required.', False)

        try:
            price = float(price_str)
            stock = int(stock_str)
        except ValueError:
            raise self._redirect_products('Invalid price or stock value.', False)

        image_b64 = await self._read_upload_image(data)

        from bot.database.methods.create import create_item
        try:
            create_item(name, description, price, category)
            with Database().session() as s:
                goods = s.query(Goods).filter_by(name=name).first()
                if goods:
                    if stock > 0:
                        goods.stock_quantity = stock
                        s.add(InventoryLog(
                            item_name=name, change_type='add',
                            quantity_change=stock,
                            comment="Initial stock via dashboard",
                        ))
                    if image_b64:
                        goods.image = image_b64
            raise self._redirect_products(f'Product "{name}" added.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_products(f'Error adding product: {e}', False)

    async def products_update_handler(self, request):
        """POST: update a product."""
        data = await request.post()
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()
        description = data.get('description', '').strip()
        price_str = data.get('price', '0')
        category = data.get('category', '').strip()

        if not old_name or not new_name or not description or not category:
            raise self._redirect_products('All fields are required.', False)

        try:
            price = float(price_str)
        except ValueError:
            raise self._redirect_products('Invalid price.', False)

        image_b64 = await self._read_upload_image(data)

        from bot.database.methods.update import update_item
        success, error = update_item(old_name, new_name, description, price, category)
        if success:
            if image_b64:
                with Database().session() as s:
                    goods = s.query(Goods).filter_by(name=new_name).first()
                    if goods:
                        goods.image = image_b64
            raise self._redirect_products(f'Product "{new_name}" updated.')
        else:
            raise self._redirect_products(f'Update failed: {error}', False)

    async def products_delete_handler(self, request):
        """POST: delete a product."""
        data = await request.post()
        name = data.get('name', '').strip()
        if not name:
            raise self._redirect_products('Product name required.', False)

        from bot.database.methods.delete import delete_item
        try:
            delete_item(name)
            raise self._redirect_products(f'Product "{name}" deleted.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_products(f'Error: {e}', False)

    async def products_stock_handler(self, request):
        """POST: manage stock (add / set / remove)."""
        data = await request.post()
        item_name = data.get('item_name', '').strip()
        action = data.get('action', 'add')

        try:
            quantity = int(data.get('quantity', 0))
        except ValueError:
            raise self._redirect_products('Invalid quantity.', False)

        if not item_name or quantity < 0:
            raise self._redirect_products('Item name and positive quantity required.', False)

        try:
            with Database().session() as s:
                goods = s.query(Goods).filter_by(name=item_name).first()
                if not goods:
                    raise self._redirect_products(f'Item "{item_name}" not found.', False)

                if action == 'add':
                    goods.stock_quantity += quantity
                    msg = f'Added {quantity} to "{item_name}" stock.'
                elif action == 'set':
                    if quantity < goods.reserved_quantity:
                        raise self._redirect_products(
                            f'Cannot set stock below reserved ({goods.reserved_quantity}).', False)
                    goods.stock_quantity = quantity
                    msg = f'Set "{item_name}" stock to {quantity}.'
                elif action == 'remove':
                    available = goods.stock_quantity - goods.reserved_quantity
                    if quantity > available:
                        raise self._redirect_products(
                            f'Cannot remove {quantity}, only {available} available.', False)
                    goods.stock_quantity -= quantity
                    msg = f'Removed {quantity} from "{item_name}" stock.'
                else:
                    raise self._redirect_products('Unknown action.', False)

                # Log the change
                log_entry = InventoryLog(
                    item_name=item_name,
                    change_type='manual',
                    quantity_change=quantity if action != 'remove' else -quantity,
                    comment=f"Dashboard: {action} {quantity}",
                )
                s.add(log_entry)

            raise self._redirect_products(msg)
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_products(f'Stock error: {e}', False)

    async def categories_add_handler(self, request):
        """POST: add a category."""
        data = await request.post()
        name = data.get('name', '').strip()
        if not name:
            raise self._redirect_products('Category name required.', False)

        from bot.database.methods.create import create_category
        try:
            create_category(name)
            raise self._redirect_products(f'Category "{name}" added.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_products(f'Error: {e}', False)

    async def categories_rename_handler(self, request):
        """POST: rename a category."""
        data = await request.post()
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()
        if not old_name or not new_name:
            raise self._redirect_products('Both old and new name required.', False)

        from bot.database.methods.update import update_category
        try:
            update_category(old_name, new_name)
            raise self._redirect_products(f'Category renamed to "{new_name}".')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_products(f'Rename failed: {e}', False)

    async def categories_delete_handler(self, request):
        """POST: delete a category."""
        data = await request.post()
        name = data.get('name', '').strip()
        if not name:
            raise self._redirect_products('Category name required.', False)

        from bot.database.methods.delete import delete_category
        try:
            delete_category(name)
            raise self._redirect_products(f'Category "{name}" deleted.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_products(f'Error: {e}', False)

    # ── Settings ────────────────────────────────────────────────────

    @staticmethod
    def _redirect_settings(msg: str = '', ok: bool = True):
        from urllib.parse import quote
        url = f'/settings?msg={quote(msg)}&ok={"1" if ok else "0"}' if msg else '/settings'
        return web.HTTPFound(url)

    async def settings_handler(self, request):
        """Settings management page."""
        flash_msg = request.query.get('msg', '')
        flash_ok = request.query.get('ok', '1') == '1'

        try:
            from bot.database.methods.read import get_reference_bonus_percent, get_bot_setting
            from bot.config import timezone as tz_mod

            referral_pct = get_reference_bonus_percent()
            order_timeout = get_bot_setting('cash_order_timeout_hours', default='24', value_type=int)
            current_tz = tz_mod.get_timezone()
            has_banner = bool(get_bot_setting('start_banner_image'))
            cod_enabled = get_bot_setting('cod_enabled', default='true').lower() != 'false'
            banner_preview = ''
            if has_banner:
                with Database().session() as s:
                    b = s.query(BotSettings).filter_by(setting_key='start_banner_image').first()
                    if b and b.setting_value:
                        banner_preview = f'<img src="data:image/png;base64,{b.setting_value}" style="max-width:300px;max-height:200px;border-radius:8px;margin-top:10px;display:block">'
        except Exception as e:
            logger.error(f"Settings load error: {e}")
            referral_pct, order_timeout, current_tz, has_banner, banner_preview = 0, 24, 'UTC', False, ''
            cod_enabled = True

        flash_html = ''
        if flash_msg:
            cls = 'ok' if flash_ok else 'err'
            flash_html = f'<div class="pm-flash {cls}">{flash_msg}</div>'

        timezones = ['UTC', 'Europe/London', 'Europe/Berlin', 'Europe/Moscow',
                     'America/New_York', 'America/Chicago', 'America/Los_Angeles',
                     'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Dubai', 'Australia/Sydney']
        tz_opts = ''.join(f'<option value="{t}" {"selected" if t == current_tz else ""}>{t}</option>' for t in timezones)

        content = self._products_page_css() + flash_html + f'''
        <h2>Settings</h2>
        <div class="pm-section">
            <h3>General Settings</h3>
            <form class="pm-form" method="POST" action="/settings/update" style="flex-direction:column;align-items:stretch;gap:16px">
                <div style="display:flex;flex-wrap:wrap;gap:16px">
                    <label>Referral Bonus %
                        <input name="referral_percent" type="number" min="0" max="100" value="{referral_pct}" style="width:120px">
                    </label>
                    <label>Order Timeout (hours)
                        <input name="order_timeout" type="number" min="1" max="168" value="{order_timeout}" style="width:120px">
                    </label>
                    <label>Timezone
                        <select name="timezone">{tz_opts}
                            <option value="__custom">Custom...</option>
                        </select>
                    </label>
                    <label>Custom TZ <input name="custom_timezone" placeholder="e.g. Europe/Rome" style="width:180px"></label>
                </div>
                <div><button class="pm-btn pm-btn-primary" type="submit">Save Settings</button></div>
            </form>
        </div>

        <div class="pm-section">
            <h3>Cash on Delivery {'<span class="status-ok">ENABLED</span>' if cod_enabled else '<span style="color:#7a7f8a">DISABLED</span>'}</h3>
            <p style="margin-bottom:12px;color:#7a7f8a">When disabled, only crypto payments are available at checkout.</p>
            <form method="POST" action="/settings/update">
                <input type="hidden" name="referral_percent" value="{referral_pct}">
                <input type="hidden" name="order_timeout" value="{order_timeout}">
                <input type="hidden" name="timezone" value="{current_tz}">
                <input type="hidden" name="cod_enabled" value="{'false' if cod_enabled else 'true'}">
                <button class="pm-btn {'pm-btn-danger' if cod_enabled else 'pm-btn-success'}" type="submit">
                    {'Disable' if cod_enabled else 'Enable'} Cash on Delivery
                </button>
            </form>
        </div>

        <div class="pm-section">
            <h3>Start Banner Image</h3>
            <p style="margin-bottom:12px;color:#7a7f8a">This image is displayed when users send /start to the bot.</p>
            {'<p><strong>Current banner:</strong></p>' + banner_preview if has_banner else '<p style="color:#7a7f8a">No banner set.</p>'}
            <form class="pm-form" method="POST" action="/settings/banner" enctype="multipart/form-data" style="margin-top:12px">
                <label>Upload image <input name="image" type="file" accept="image/*"></label>
                <button class="pm-btn pm-btn-primary pm-btn-sm" type="submit">Set Banner</button>
                <button class="pm-btn pm-btn-danger pm-btn-sm" type="submit" name="action" value="clear">Remove Banner</button>
            </form>
        </div>

        <div class="pm-section">
            <h3>Data Export / Import</h3>
            <div style="display:flex;flex-wrap:wrap;gap:24px">
                <div>
                    <h4 style="color:#d0d3da;margin-bottom:8px">Shop Data</h4>
                    <p style="color:#7a7f8a;font-size:.85em;margin-bottom:10px">Categories, products, stock levels, and images.</p>
                    <div style="display:flex;gap:8px;align-items:start">
                        <a href="/export/shop" class="pm-btn pm-btn-primary pm-btn-sm" download>Export JSON</a>
                        <form method="POST" action="/import/shop" enctype="multipart/form-data" style="display:flex;gap:6px;align-items:end">
                            <input type="file" name="file" accept=".json" style="max-width:180px;font-size:.8em;color:#7a7f8a">
                            <button class="pm-btn pm-btn-warn pm-btn-sm" type="submit"
                                    onclick="return confirm('Import will merge with existing data. Matching products will be overwritten. Continue?')">Import</button>
                        </form>
                    </div>
                </div>
                <div>
                    <h4 style="color:#d0d3da;margin-bottom:8px">Order Data</h4>
                    <p style="color:#7a7f8a;font-size:.85em;margin-bottom:10px">All orders with items, status, and payment details.</p>
                    <div style="display:flex;gap:8px;align-items:start">
                        <a href="/export/orders" class="pm-btn pm-btn-primary pm-btn-sm" download>Export JSON</a>
                        <form method="POST" action="/import/orders" enctype="multipart/form-data" style="display:flex;gap:6px;align-items:end">
                            <input type="file" name="file" accept=".json" style="max-width:180px;font-size:.8em;color:#7a7f8a">
                            <button class="pm-btn pm-btn-warn pm-btn-sm" type="submit"
                                    onclick="return confirm('Import will add orders that do not already exist (matched by order_code). Continue?')">Import</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        '''
        html = self._get_base_html("Settings", content, "settings")
        html = html.replace('<meta http-equiv="refresh" content="10">', '')
        return web.Response(text=html, content_type='text/html')

    async def settings_update_handler(self, request):
        """POST: update general settings."""
        data = await request.post()
        try:
            referral_pct = int(data.get('referral_percent', 0))
            order_timeout = int(data.get('order_timeout', 24))
            tz_select = data.get('timezone', 'UTC')
            custom_tz = data.get('custom_timezone', '').strip()
            chosen_tz = custom_tz if (tz_select == '__custom' and custom_tz) else tz_select

            settings_map = {
                'reference_bonus_percent': str(max(0, min(100, referral_pct))),
                'cash_order_timeout_hours': str(max(1, min(168, order_timeout))),
                'timezone': chosen_tz,
            }

            # Optional toggles passed as hidden fields
            for toggle_key in ('cod_enabled', 'testnet_user_wallets'):
                val = data.get(toggle_key, '').strip()
                if val in ('true', 'false'):
                    settings_map[toggle_key] = val

            # Per-currency enabled flags
            for key in list(data.keys()):
                if key.startswith('currency_enabled_'):
                    settings_map[key] = data[key]

            with Database().session() as s:
                for key, val in settings_map.items():
                    setting = s.query(BotSettings).filter_by(setting_key=key).first()
                    if setting:
                        setting.setting_value = val
                    else:
                        s.add(BotSettings(setting_key=key, setting_value=val))

            # Hot reload timezone
            from bot.config import timezone as tz_mod
            tz_mod.reload_timezone()

            raise self._redirect_settings('Settings saved.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_settings(f'Error: {e}', False)

    async def settings_banner_handler(self, request):
        """POST: set or clear banner image."""
        data = await request.post()
        action = data.get('action', '')

        if action == 'clear':
            with Database().session() as s:
                setting = s.query(BotSettings).filter_by(setting_key='start_banner_image').first()
                if setting:
                    s.delete(setting)
            raise self._redirect_settings('Banner removed.')

        image_b64 = await self._read_upload_image(data)
        if not image_b64:
            raise self._redirect_settings('No image selected.', False)

        with Database().session() as s:
            setting = s.query(BotSettings).filter_by(setting_key='start_banner_image').first()
            if setting:
                setting.setting_value = image_b64
            else:
                s.add(BotSettings(setting_key='start_banner_image', setting_value=image_b64))

        raise self._redirect_settings('Banner updated.')

    # ── Users ─────────────────────────────────────────────────────

    @staticmethod
    def _redirect_users(msg: str = '', ok: bool = True):
        from urllib.parse import quote
        url = f'/users?msg={quote(msg)}&ok={"1" if ok else "0"}' if msg else '/users'
        return web.HTTPFound(url)

    async def users_handler(self, request):
        """Users management page with list and search."""
        flash_msg = request.query.get('msg', '')
        flash_ok = request.query.get('ok', '1') == '1'
        search_q = request.query.get('q', '').strip()
        page = int(request.query.get('page', '0'))
        per_page = 25

        flash_html = ''
        if flash_msg:
            cls = 'ok' if flash_ok else 'err'
            flash_html = f'<div class="pm-flash {cls}">{flash_msg}</div>'

        try:
            with Database().session() as s:
                total_users = s.query(func.count(User.telegram_id)).scalar() or 0
                total_admins = s.query(func.count(User.telegram_id)).filter(User.role_id > 1).scalar() or 0
                total_banned = s.query(func.count(User.telegram_id)).filter(User.is_banned == True).scalar() or 0

                query = s.query(User, Role.name.label('role_name')).join(Role, User.role_id == Role.id)
                if search_q:
                    if search_q.isdigit():
                        query = query.filter(User.telegram_id == int(search_q))
                    else:
                        query = query.filter(User.is_banned == True) if search_q.lower() == 'banned' else query

                total_filtered = query.count()
                users = query.order_by(User.registration_date.desc()).offset(page * per_page).limit(per_page).all()

                user_list = []
                for u, role_name in users:
                    # Get customer info if exists
                    ci = s.query(CustomerInfo).filter_by(telegram_id=u.telegram_id).first()
                    user_list.append({
                        'id': u.telegram_id,
                        'role': role_name,
                        'role_id': u.role_id,
                        'registered': u.registration_date.strftime('%Y-%m-%d') if u.registration_date else '?',
                        'banned': u.is_banned,
                        'ban_reason': u.ban_reason or '',
                        'bonus': ci.bonus_balance if ci else 0,
                        'orders': ci.completed_orders_count if ci else 0,
                        'spent': ci.total_spendings if ci else 0,
                    })
        except Exception as e:
            logger.error(f"Users load error: {e}")
            total_users = total_admins = total_banned = total_filtered = 0
            user_list = []

        # Stats cards
        stats_html = f'''
        <div class="metric-grid">
            <div class="metric-card"><div class="metric-label">Total Users</div><div class="metric-value">{total_users}</div></div>
            <div class="metric-card"><div class="metric-label">Admins</div><div class="metric-value">{total_admins}</div></div>
            <div class="metric-card"><div class="metric-label">Banned</div><div class="metric-value" style="color:#ef5350">{total_banned}</div></div>
        </div>'''

        # Search
        search_html = f'''
        <div class="pm-section">
            <form class="pm-form" method="GET" action="/users">
                <label>Search by Telegram ID or type "banned"
                    <input name="q" value="{search_q}" placeholder="Telegram ID..." style="width:250px">
                </label>
                <button class="pm-btn pm-btn-primary pm-btn-sm" type="submit">Search</button>
                {"<a href='/users' style='padding:8px;font-size:.85em'>Clear</a>" if search_q else ""}
            </form>
        </div>'''

        # Users table
        table_html = '<div class="pm-section"><h3>Users</h3>'
        if user_list:
            table_html += '<table class="pm-table"><thead><tr>'
            table_html += '<th>ID</th><th>Role</th><th>Registered</th><th>Orders</th><th>Spent</th><th>Bonus</th><th>Status</th><th>Actions</th>'
            table_html += '</tr></thead><tbody>'
            for u in user_list:
                status = '<span style="color:#ef5350">BANNED</span>' if u['banned'] else '<span class="status-ok">Active</span>'
                table_html += f'''<tr>
                    <td><strong>{u["id"]}</strong></td>
                    <td>{u["role"]}</td>
                    <td>{u["registered"]}</td>
                    <td>{u["orders"]}</td>
                    <td>{u["spent"]}</td>
                    <td>{u["bonus"]}</td>
                    <td>{status}</td>
                    <td class="pm-actions">
                        <form method="POST" action="/users/ban" style="display:inline">
                            <input type="hidden" name="user_id" value="{u["id"]}">
                            {"<button class='pm-btn pm-btn-success pm-btn-sm' name='action' value='unban' type='submit'>Unban</button>" if u["banned"] else "<button class='pm-btn pm-btn-danger pm-btn-sm' name='action' value='ban' type='submit'>Ban</button>"}
                        </form>
                        <form method="POST" action="/users/role" style="display:inline">
                            <input type="hidden" name="user_id" value="{u["id"]}">
                            {"<button class='pm-btn pm-btn-warn pm-btn-sm' name='action' value='demote' type='submit'>Demote</button>" if u["role_id"] > 1 and u["role"] != "OWNER" else ""}
                            {"<button class='pm-btn pm-btn-primary pm-btn-sm' name='action' value='promote' type='submit'>Promote</button>" if u["role_id"] == 1 else ""}
                        </form>
                    </td>
                </tr>'''
            table_html += '</tbody></table>'

            # Pagination
            total_pages = (total_filtered + per_page - 1) // per_page
            if total_pages > 1:
                q_param = f'&q={search_q}' if search_q else ''
                table_html += '<div style="margin-top:16px;display:flex;gap:8px;align-items:center">'
                if page > 0:
                    table_html += f'<a href="/users?page={page-1}{q_param}" class="pm-btn pm-btn-primary pm-btn-sm">Prev</a>'
                table_html += f'<span style="color:#7a7f8a">Page {page+1}/{total_pages}</span>'
                if page < total_pages - 1:
                    table_html += f'<a href="/users?page={page+1}{q_param}" class="pm-btn pm-btn-primary pm-btn-sm">Next</a>'
                table_html += '</div>'
        else:
            table_html += '<p>No users found.</p>'
        table_html += '</div>'

        content = self._products_page_css() + flash_html + stats_html + search_html + table_html
        html = self._get_base_html("Users", content, "users")
        html = html.replace('<meta http-equiv="refresh" content="10">', '')
        return web.Response(text=html, content_type='text/html')

    async def users_role_handler(self, request):
        """POST: promote/demote user."""
        data = await request.post()
        user_id = int(data.get('user_id', 0))
        action = data.get('action', '')

        try:
            with Database().session() as s:
                if action == 'promote':
                    admin_role = s.query(Role).filter_by(name='ADMIN').first()
                    if admin_role:
                        s.query(User).filter_by(telegram_id=user_id).update({User.role_id: admin_role.id})
                        raise self._redirect_users(f'User {user_id} promoted to ADMIN.')
                elif action == 'demote':
                    user_role = s.query(Role).filter_by(name='USER').first()
                    if user_role:
                        s.query(User).filter_by(telegram_id=user_id).update({User.role_id: user_role.id})
                        raise self._redirect_users(f'User {user_id} demoted to USER.')
            raise self._redirect_users('Unknown action.', False)
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_users(f'Error: {e}', False)

    async def users_ban_handler(self, request):
        """POST: ban/unban user."""
        data = await request.post()
        user_id = int(data.get('user_id', 0))
        action = data.get('action', '')

        try:
            with Database().session() as s:
                user = s.query(User).filter_by(telegram_id=user_id).first()
                if not user:
                    raise self._redirect_users(f'User {user_id} not found.', False)

                if action == 'ban':
                    user.is_banned = True
                    user.banned_at = datetime.now(dt_tz.utc)
                    user.ban_reason = 'Banned via dashboard'
                    raise self._redirect_users(f'User {user_id} banned.')
                elif action == 'unban':
                    user.is_banned = False
                    user.banned_at = None
                    user.ban_reason = None
                    raise self._redirect_users(f'User {user_id} unbanned.')
            raise self._redirect_users('Unknown action.', False)
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_users(f'Error: {e}', False)

    # ── Reference Codes ───────────────────────────────────────────

    @staticmethod
    def _redirect_refcodes(msg: str = '', ok: bool = True):
        from urllib.parse import quote
        url = f'/refcodes?msg={quote(msg)}&ok={"1" if ok else "0"}' if msg else '/refcodes'
        return web.HTTPFound(url)

    async def refcodes_handler(self, request):
        """Reference codes management page."""
        flash_msg = request.query.get('msg', '')
        flash_ok = request.query.get('ok', '1') == '1'

        flash_html = ''
        if flash_msg:
            cls = 'ok' if flash_ok else 'err'
            flash_html = f'<div class="pm-flash {cls}">{flash_msg}</div>'

        try:
            with Database().session() as s:
                codes = s.query(ReferenceCode).order_by(ReferenceCode.created_at.desc()).limit(50).all()
                refcodes_enabled_setting = s.query(BotSettings).filter_by(setting_key='reference_codes_enabled').first()
                refcodes_enabled = refcodes_enabled_setting and refcodes_enabled_setting.setting_value.lower() == 'true' if refcodes_enabled_setting else True

                code_list = []
                for c in codes:
                    code_list.append({
                        'code': c.code,
                        'active': c.is_active,
                        'admin': c.is_admin_code,
                        'grants_admin': getattr(c, 'grants_admin', False),
                        'uses': c.current_uses,
                        'max_uses': c.max_uses,
                        'expires': c.expires_at.strftime('%Y-%m-%d %H:%M') if c.expires_at else 'Never',
                        'note': c.note or '',
                        'created': c.created_at.strftime('%Y-%m-%d') if c.created_at else '',
                    })
        except Exception as e:
            logger.error(f"Refcodes load error: {e}")
            code_list = []
            refcodes_enabled = True

        toggle_label = 'Disable' if refcodes_enabled else 'Enable'
        toggle_cls = 'pm-btn-danger' if refcodes_enabled else 'pm-btn-success'
        status_text = '<span class="status-ok">REQUIRED</span>' if refcodes_enabled else '<span style="color:#7a7f8a">DISABLED</span>'

        # Create form
        create_html = f'''
        <div class="pm-section">
            <h3>Reference Codes {status_text}</h3>
            <form method="POST" action="/refcodes/toggle" style="display:inline;margin-bottom:16px">
                <button class="pm-btn {toggle_cls} pm-btn-sm" type="submit">{toggle_label} Ref Codes</button>
            </form>
        </div>
        <div class="pm-section">
            <h3>Create Code</h3>
            <form class="pm-form" method="POST" action="/refcodes/create">
                <label>Expires in (hours, 0=never) <input name="expires_hours" type="number" min="0" value="0" style="width:120px"></label>
                <label>Max uses (0=unlimited) <input name="max_uses" type="number" min="0" value="0" style="width:120px"></label>
                <label>Note <input name="note" placeholder="optional" style="width:200px"></label>
                <button class="pm-btn pm-btn-primary" type="submit">Create</button>
            </form>
        </div>
        <div class="pm-section">
            <h3>Create Admin Invite Code</h3>
            <p style="margin-bottom:12px;color:#7a7f8a">Single-use, expires in 1 hour. User who redeems this code is granted the ADMIN role.</p>
            <form class="pm-form" method="POST" action="/refcodes/create">
                <input type="hidden" name="grants_admin" value="true">
                <input type="hidden" name="expires_hours" value="1">
                <input type="hidden" name="max_uses" value="1">
                <label>Note <input name="note" placeholder="e.g. For @username" style="width:250px"></label>
                <button class="pm-btn pm-btn-warn" type="submit">Create Admin Code</button>
            </form>
        </div>'''

        # Codes table
        table_html = '<div class="pm-section"><h3>Existing Codes</h3>'
        if code_list:
            table_html += '<table class="pm-table"><thead><tr>'
            table_html += '<th>Code</th><th>Type</th><th>Uses</th><th>Expires</th><th>Note</th><th>Created</th><th>Status</th>'
            table_html += '</tr></thead><tbody>'
            for c in code_list:
                status = '<span class="status-ok">Active</span>' if c['active'] else '<span style="color:#7a7f8a">Inactive</span>'
                ctype = '<span style="color:#ffa726">Admin Invite</span>' if c['grants_admin'] else ('Admin' if c['admin'] else 'User')
                max_u = str(c['max_uses']) if c['max_uses'] else 'Unlimited'
                table_html += f'''<tr>
                    <td><code style="color:#7b8cff;font-size:1.05em">{c["code"]}</code></td>
                    <td>{ctype}</td>
                    <td>{c["uses"]}/{max_u}</td>
                    <td>{c["expires"]}</td>
                    <td>{c["note"]}</td>
                    <td>{c["created"]}</td>
                    <td>{status}</td>
                </tr>'''
            table_html += '</tbody></table>'
        else:
            table_html += '<p>No reference codes yet.</p>'
        table_html += '</div>'

        content = self._products_page_css() + flash_html + create_html + table_html
        html = self._get_base_html("Reference Codes", content, "refcodes")
        html = html.replace('<meta http-equiv="refresh" content="10">', '')
        return web.Response(text=html, content_type='text/html')

    async def refcodes_create_handler(self, request):
        """POST: create a reference code."""
        data = await request.post()
        try:
            expires_hours = int(data.get('expires_hours', 0))
            max_uses = int(data.get('max_uses', 0))
            note = data.get('note', '').strip() or None
            grants_admin = data.get('grants_admin', '').lower() == 'true'

            from bot.referrals import create_reference_code
            code = create_reference_code(
                created_by=int(EnvKeys.OWNER_ID),
                created_by_username='dashboard',
                is_admin_code=True,
                expires_in_hours=expires_hours if expires_hours > 0 else None,
                max_uses=max_uses if max_uses > 0 else None,
                note=note,
                grants_admin=grants_admin,
            )
            label = 'Admin invite' if grants_admin else 'Code'
            raise self._redirect_refcodes(f'{label} created: {code}')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_refcodes(f'Error: {e}', False)

    async def refcodes_toggle_handler(self, request):
        """POST: toggle reference codes requirement."""
        try:
            with Database().session() as s:
                setting = s.query(BotSettings).filter_by(setting_key='reference_codes_enabled').first()
                if setting:
                    current = setting.setting_value.lower() == 'true'
                    setting.setting_value = 'false' if current else 'true'
                else:
                    s.add(BotSettings(setting_key='reference_codes_enabled', setting_value='false'))
            raise self._redirect_refcodes('Reference codes setting toggled.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_refcodes(f'Error: {e}', False)

    # ── Wallets ───────────────────────────────────────────────────

    @staticmethod
    def _redirect_wallets(msg: str = '', ok: bool = True):
        from urllib.parse import quote
        url = f'/wallets?msg={quote(msg)}&ok={"1" if ok else "0"}' if msg else '/wallets'
        return web.HTTPFound(url)

    # All supported currencies with display names
    ALL_CURRENCIES = [
        ("BTC", "Bitcoin (BTC)"),
        ("LTC", "Litecoin (LTC)"),
        ("ETH", "Ethereum (ETH)"),
        ("USDT-ERC20", "USDT (ERC20)"),
        ("USDC-ERC20", "USDC (ERC20)"),
        ("SOL", "Solana (SOL)"),
        ("USDT-SPL", "USDT (SPL)"),
        ("USDC-SPL", "USDC (SPL)"),
        ("TRX", "Tron (TRX)"),
        ("USDT-TRC20", "USDT (TRC20)"),
        ("USDC-TRC20", "USDC (TRC20)"),
    ]

    async def wallets_handler(self, request):
        """Wallet management page."""
        flash_msg = request.query.get('msg', '')
        flash_ok = request.query.get('ok', '1') == '1'

        flash_html = ''
        if flash_msg:
            cls = 'ok' if flash_ok else 'err'
            flash_html = f'<div class="pm-flash {cls}">{flash_msg}</div>'

        try:
            from bot.database.methods.read import get_bot_setting
            auto_feed = get_bot_setting("wallet_auto_feed", default="false").lower() == "true"
            testnet_wallets = get_bot_setting("testnet_user_wallets", default="false").lower() == "true"
            is_testnet = EnvKeys.USE_TESTNET

            # Per-currency enabled flags (default all enabled)
            currency_states = {}
            for code, label in self.ALL_CURRENCIES:
                key = f"currency_enabled_{code}"
                enabled = get_bot_setting(key, default="true").lower() != "false"
                currency_states[code] = {'label': label, 'enabled': enabled}

            with Database().session() as s:
                chain_stats = []
                for chain_row in s.query(CryptoAddress.chain).distinct().all():
                    chain = chain_row[0]
                    total = s.query(func.count(CryptoAddress.id)).filter_by(chain=chain).scalar() or 0
                    available = s.query(func.count(CryptoAddress.id)).filter(
                        CryptoAddress.chain == chain, CryptoAddress.is_used == False
                    ).scalar() or 0
                    used = total - available
                    chain_stats.append({'chain': chain, 'total': total, 'available': available, 'used': used})

        except Exception as e:
            logger.error(f"Wallets load error: {e}")
            auto_feed = False
            testnet_wallets = False
            is_testnet = False
            chain_stats = []
            currency_states = {c: {'label': l, 'enabled': True} for c, l in self.ALL_CURRENCIES}

        # ── Receiving wallets key status ──
        from bot.payments.wallets import WalletManager
        wm = WalletManager()
        wallet_chains = ['BTC', 'ETH', 'LTC', 'SOL', 'TRX']
        wallet_status = []
        for wc in wallet_chains:
            pub_path = wm.get_public_file(wc)
            priv_path = wm.get_private_file(wc)
            pub_exists = pub_path.exists()
            priv_exists = priv_path.exists()
            created = None
            if pub_exists:
                try:
                    import os
                    created = datetime.fromtimestamp(os.path.getmtime(pub_path), tz=dt_tz.utc).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    created = '?'
            wallet_status.append({
                'chain': wc,
                'pub': pub_exists,
                'priv': priv_exists,
                'created': created,
                'pub_path': str(pub_path),
                'priv_path': str(priv_path),
            })

        # Build receiving wallets HTML
        rw_html = '<div class="pm-section"><h3>Receiving Wallets (Shop Keys)</h3>'
        rw_html += '<p style="margin-bottom:14px;color:#7a7f8a">These keys are used to derive deposit addresses for customer orders. Private key backup is essential for fund recovery.</p>'
        rw_html += '<table class="pm-table"><thead><tr><th>Chain</th><th>Public Key</th><th>Private Key</th><th>Created</th><th>Actions</th></tr></thead><tbody>'

        for ws in wallet_status:
            pub_badge = '<span class="status-ok">exists</span>' if ws['pub'] else '<span class="status-error">missing</span>'
            priv_badge = '<span class="status-ok">exists</span>' if ws['priv'] else '<span style="color:#7a7f8a">none</span>'
            created_str = ws['created'] or '-'

            actions = ''
            if ws['pub']:
                actions += f'<a href="/wallets/backup/{ws["chain"]}/public" class="pm-btn pm-btn-primary pm-btn-sm" download>Backup Pub</a> '
            if ws['priv']:
                actions += f'<a href="/wallets/backup/{ws["chain"]}/private" class="pm-btn pm-btn-warn pm-btn-sm" download>Backup Priv</a> '

            if ws['pub']:
                actions += f'''
                <form method="POST" action="/wallets/generate" style="display:inline"
                      onsubmit="return confirm('DANGER: This will REPLACE the {ws["chain"]} wallet keys!\\n\\nAll existing deposit addresses will become orphaned.\\nMake sure you have backed up the current keys first.\\n\\nType the chain name to confirm:') && prompt('Type {ws["chain"]} to confirm') === '{ws["chain"]}'">
                    <input type="hidden" name="chain" value="{ws["chain"]}">
                    <button class="pm-btn pm-btn-danger pm-btn-sm" type="submit">Regenerate</button>
                </form>'''
            else:
                actions += f'''
                <form method="POST" action="/wallets/generate" style="display:inline">
                    <input type="hidden" name="chain" value="{ws["chain"]}">
                    <button class="pm-btn pm-btn-success pm-btn-sm" type="submit">Generate</button>
                </form>'''

            rw_html += f'''<tr>
                <td><strong>{ws["chain"]}</strong></td>
                <td>{pub_badge}</td>
                <td>{priv_badge}</td>
                <td>{created_str}</td>
                <td class="pm-actions">{actions}</td>
            </tr>'''

        rw_html += '</tbody></table></div>'

        # Auto-feed section
        af_toggle_cls = 'pm-btn-danger' if auto_feed else 'pm-btn-success'
        af_status = '<span class="status-ok">ENABLED</span>' if auto_feed else '<span style="color:#7a7f8a">DISABLED</span>'

        # Address pool cards
        cards_html = '<div class="metric-grid">'
        for cs in chain_stats:
            avail_cls = 'status-ok' if cs['available'] > 5 else 'status-warning' if cs['available'] > 0 else 'status-error'
            cards_html += f'''
            <div class="metric-card">
                <div class="metric-label">{cs["chain"]}</div>
                <div class="metric-value {avail_cls}">{cs["available"]}</div>
                <div style="color:#6b7080;font-size:.85em">{cs["used"]} used / {cs["total"]} total</div>
            </div>'''
        if not chain_stats:
            cards_html += '<div class="metric-card"><p>No crypto addresses loaded.</p></div>'
        cards_html += '</div>'

        # Currency switches
        curr_html = '<div class="pm-section"><h3>Accepted Currencies</h3>'
        curr_html += '<p style="margin-bottom:14px;color:#7a7f8a">Toggle which cryptocurrencies are shown at checkout.</p>'
        curr_html += '<form method="POST" action="/wallets/currencies"><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px">'
        for code, info in currency_states.items():
            checked = 'checked' if info['enabled'] else ''
            curr_html += f'''
            <label style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#15171c;border-radius:8px;border:1px solid #2a2d35;cursor:pointer">
                <input type="checkbox" name="currency_{code}" value="true" {checked}
                       style="width:18px;height:18px;accent-color:#7b8cff">
                <span style="color:#c8ccd4;font-size:.9em">{info["label"]}</span>
            </label>'''
        curr_html += '</div><button class="pm-btn pm-btn-primary pm-btn-sm" type="submit" style="margin-top:14px">Save Currencies</button></form></div>'

        # Testnet wallets section (only in testnet mode)
        tw_html = ''
        if is_testnet:
            tw_status = '<span class="status-ok">ENABLED</span>' if testnet_wallets else '<span style="color:#7a7f8a">DISABLED</span>'
            tw_cls = 'pm-btn-danger' if testnet_wallets else 'pm-btn-success'
            tw_html = f'''
            <div class="pm-section">
                <h3>Testnet User Wallets {tw_status}</h3>
                <p style="margin-bottom:12px;color:#7a7f8a">
                    Creates a crypto wallet per user at checkout. Users top up via faucet, bot sends payment automatically.
                    <strong>Testnet only.</strong>
                </p>
                <form method="POST" action="/wallets/toggle-testnet-wallets">
                    <button class="pm-btn {tw_cls}" type="submit">{'Disable' if testnet_wallets else 'Enable'} Testnet Wallets</button>
                </form>
            </div>'''

        content = self._products_page_css() + flash_html + f'''
        <h2>Wallet Management</h2>
        <div class="pm-section">
            <h3>Auto-Feed {af_status}</h3>
            <p style="margin-bottom:12px;color:#7a7f8a">When enabled, address pools are automatically replenished every hour.</p>
            <form method="POST" action="/wallets/toggle-autofeed">
                <button class="pm-btn {af_toggle_cls}" type="submit">{"Disable" if auto_feed else "Enable"} Auto-Feed</button>
            </form>
        </div>
        {rw_html}
        {tw_html}
        {curr_html}
        <h3 style="margin-bottom:16px">Address Pools</h3>
        {cards_html}
        '''
        html = self._get_base_html("Wallets", content, "wallets")
        html = html.replace('<meta http-equiv="refresh" content="10">', '')
        return web.Response(text=html, content_type='text/html')

    async def wallets_toggle_autofeed_handler(self, request):
        """POST: toggle wallet auto-feed."""
        try:
            from bot.database.methods.read import get_bot_setting
            current = get_bot_setting("wallet_auto_feed", default="false").lower() == "true"
            new_val = "false" if current else "true"

            with Database().session() as s:
                setting = s.query(BotSettings).filter_by(setting_key="wallet_auto_feed").first()
                if setting:
                    setting.setting_value = new_val
                else:
                    s.add(BotSettings(setting_key="wallet_auto_feed", setting_value=new_val))

            raise self._redirect_wallets(f'Auto-feed {"enabled" if new_val == "true" else "disabled"}.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_wallets(f'Error: {e}', False)

    async def wallets_toggle_testnet_handler(self, request):
        """POST: toggle testnet user wallets."""
        try:
            from bot.database.methods.read import get_bot_setting
            current = get_bot_setting("testnet_user_wallets", default="false").lower() == "true"
            new_val = "false" if current else "true"

            with Database().session() as s:
                setting = s.query(BotSettings).filter_by(setting_key="testnet_user_wallets").first()
                if setting:
                    setting.setting_value = new_val
                else:
                    s.add(BotSettings(setting_key="testnet_user_wallets", setting_value=new_val))

            raise self._redirect_wallets(f'Testnet wallets {"enabled" if new_val == "true" else "disabled"}.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_wallets(f'Error: {e}', False)

    async def wallets_currencies_handler(self, request):
        """POST: save per-currency enabled/disabled flags."""
        data = await request.post()
        try:
            with Database().session() as s:
                for code, _ in self.ALL_CURRENCIES:
                    key = f"currency_enabled_{code}"
                    enabled = "true" if data.get(f"currency_{code}") else "false"
                    setting = s.query(BotSettings).filter_by(setting_key=key).first()
                    if setting:
                        setting.setting_value = enabled
                    else:
                        s.add(BotSettings(setting_key=key, setting_value=enabled))

            raise self._redirect_wallets('Currency settings saved.')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_wallets(f'Error: {e}', False)

    async def wallets_generate_handler(self, request):
        """POST: generate (or regenerate) receiving wallet keys for a chain."""
        data = await request.post()
        chain = data.get('chain', '').strip().upper()
        if not chain:
            raise self._redirect_wallets('Chain required.', False)

        try:
            from bot.payments.wallets import WalletManager
            wm = WalletManager()
            mnemonic, pub_key, priv_key = wm.generate_keypair(chain)

            raise self._redirect_wallets(
                f'{chain} wallet generated. Mnemonic: {mnemonic}  —  back up your private key immediately!')
        except web.HTTPFound:
            raise
        except Exception as e:
            raise self._redirect_wallets(f'Error generating {chain} wallet: {e}', False)

    async def wallets_backup_handler(self, request):
        """GET: download public or private key file for a chain."""
        chain = request.match_info.get('chain', '').upper()
        kind = request.match_info.get('kind', '')  # 'public' or 'private'

        if kind not in ('public', 'private'):
            raise self._redirect_wallets('Invalid key type.', False)

        from bot.payments.wallets import WalletManager
        wm = WalletManager()

        if kind == 'public':
            path = wm.get_public_file(chain)
            filename = f'{chain.lower()}_xpub.txt'
        else:
            path = wm.get_private_file(chain)
            filename = f'{chain.lower()}_private_BACKUP.txt'

        if not path.exists():
            raise self._redirect_wallets(f'{chain} {kind} key file not found.', False)

        content = path.read_text()
        return web.Response(
            body=content,
            content_type='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )

    # ── Export / Import ───────────────────────────────────────────

    async def export_shop_handler(self, request):
        """GET: export categories + products as JSON download."""
        try:
            with Database().session() as s:
                categories = [c.name for c in s.query(Categories).order_by(Categories.name).all()]
                products = []
                for g in s.query(Goods).order_by(Goods.name).all():
                    products.append({
                        'name': g.name,
                        'price': float(g.price),
                        'description': g.description,
                        'category': g.category_name,
                        'stock_quantity': g.stock_quantity,
                        'reserved_quantity': g.reserved_quantity,
                        'image': g.image,
                    })

            payload = json.dumps({
                'type': 'shop_data',
                'categories': categories,
                'products': products,
            }, indent=2, default=str)

            return web.Response(
                body=payload,
                content_type='application/json',
                headers={'Content-Disposition': 'attachment; filename="shop_data.json"'},
            )
        except Exception as e:
            raise self._redirect_settings(f'Export error: {e}', False)

    async def export_orders_handler(self, request):
        """GET: export all orders as JSON download."""
        try:
            with Database().session() as s:
                orders = []
                for o in s.query(Order).order_by(Order.created_at.desc()).all():
                    items = [{
                        'item_name': oi.item_name,
                        'price': float(oi.price),
                        'quantity': oi.quantity,
                    } for oi in o.items]

                    orders.append({
                        'order_code': o.order_code,
                        'buyer_id': o.buyer_id,
                        'total_price': float(o.total_price),
                        'bonus_applied': float(o.bonus_applied) if o.bonus_applied else 0,
                        'payment_method': o.payment_method,
                        'delivery_address': o.delivery_address,
                        'phone_number': o.phone_number,
                        'delivery_note': o.delivery_note,
                        'crypto_currency': o.crypto_currency,
                        'crypto_amount': float(o.crypto_amount) if o.crypto_amount else None,
                        'crypto_address': o.crypto_address,
                        'order_status': o.order_status,
                        'created_at': o.created_at.isoformat() if o.created_at else None,
                        'completed_at': o.completed_at.isoformat() if o.completed_at else None,
                        'use_testnet': o.use_testnet,
                        'items': items,
                    })

            payload = json.dumps({
                'type': 'order_data',
                'orders': orders,
            }, indent=2, default=str)

            return web.Response(
                body=payload,
                content_type='application/json',
                headers={'Content-Disposition': 'attachment; filename="orders_data.json"'},
            )
        except Exception as e:
            raise self._redirect_settings(f'Export error: {e}', False)

    async def import_shop_handler(self, request):
        """POST: import shop data from JSON. Merges: creates missing categories/products, overwrites matching ones."""
        data = await request.post()
        file_field = data.get('file')
        if not file_field or not hasattr(file_field, 'file'):
            raise self._redirect_settings('No file selected.', False)

        try:
            raw = file_field.file.read()
            payload = json.loads(raw)

            if payload.get('type') != 'shop_data':
                raise self._redirect_settings('Invalid file: expected shop_data type.', False)

            cats_imported = 0
            prods_imported = 0

            with Database().session() as s:
                # Import categories
                for cat_name in payload.get('categories', []):
                    existing = s.query(Categories).filter_by(name=cat_name).first()
                    if not existing:
                        s.add(Categories(name=cat_name))
                        cats_imported += 1

                s.flush()

                # Import products
                from decimal import Decimal
                for p in payload.get('products', []):
                    existing = s.query(Goods).filter_by(name=p['name']).first()
                    if existing:
                        existing.price = Decimal(str(p['price']))
                        existing.description = p['description']
                        existing.category_name = p['category']
                        existing.stock_quantity = p.get('stock_quantity', 0)
                        existing.reserved_quantity = p.get('reserved_quantity', 0)
                        if p.get('image'):
                            existing.image = p['image']
                    else:
                        g = Goods(
                            name=p['name'],
                            price=Decimal(str(p['price'])),
                            description=p['description'],
                            category_name=p['category'],
                            stock_quantity=p.get('stock_quantity', 0),
                        )
                        g.image = p.get('image')
                        s.add(g)
                    prods_imported += 1

            raise self._redirect_settings(
                f'Imported {cats_imported} new categories, {prods_imported} products (merged).')
        except web.HTTPFound:
            raise
        except json.JSONDecodeError:
            raise self._redirect_settings('Invalid JSON file.', False)
        except Exception as e:
            raise self._redirect_settings(f'Import error: {e}', False)

    async def import_orders_handler(self, request):
        """POST: import orders from JSON. Skips orders with existing order_codes."""
        data = await request.post()
        file_field = data.get('file')
        if not file_field or not hasattr(file_field, 'file'):
            raise self._redirect_settings('No file selected.', False)

        try:
            raw = file_field.file.read()
            payload = json.loads(raw)

            if payload.get('type') != 'order_data':
                raise self._redirect_settings('Invalid file: expected order_data type.', False)

            imported = 0
            skipped = 0
            from decimal import Decimal
            from datetime import datetime as dt

            with Database().session() as s:
                for o_data in payload.get('orders', []):
                    code = o_data.get('order_code')
                    if code and s.query(Order).filter_by(order_code=code).first():
                        skipped += 1
                        continue

                    order = Order(
                        buyer_id=o_data.get('buyer_id'),
                        total_price=Decimal(str(o_data['total_price'])),
                        bonus_applied=Decimal(str(o_data.get('bonus_applied', 0))),
                        payment_method=o_data['payment_method'],
                        delivery_address=o_data.get('delivery_address', ''),
                        phone_number=o_data.get('phone_number', ''),
                        delivery_note=o_data.get('delivery_note'),
                        crypto_currency=o_data.get('crypto_currency'),
                        crypto_amount=Decimal(str(o_data['crypto_amount'])) if o_data.get('crypto_amount') else None,
                        crypto_address=o_data.get('crypto_address'),
                        order_status=o_data.get('order_status', 'pending'),
                        order_code=code,
                        use_testnet=o_data.get('use_testnet', False),
                    )
                    s.add(order)
                    s.flush()

                    for item in o_data.get('items', []):
                        s.add(OrderItem(
                            order_id=order.id,
                            item_name=item['item_name'],
                            price=Decimal(str(item.get('price', 0))),
                            quantity=item.get('quantity', 1),
                        ))

                    imported += 1

            msg = f'Imported {imported} orders.'
            if skipped:
                msg += f' Skipped {skipped} (already exist).'
            raise self._redirect_settings(msg)
        except web.HTTPFound:
            raise
        except json.JSONDecodeError:
            raise self._redirect_settings('Invalid JSON file.', False)
        except Exception as e:
            raise self._redirect_settings(f'Import error: {e}', False)

    async def start(self):
        """Start monitoring server without access logs"""
        try:
            # Disable access logs
            import logging
            logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

            self.runner = web.AppRunner(
                self.app,
                access_log=None  # Disable access logs
            )
            await self.runner.setup()
            site = web.TCPSite(self.runner, self.host, self.port)
            await site.start()
            logger.info(f"Monitoring server started on http://{self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to start monitoring server: {e}")

    async def stop(self):
        """Stop server"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Monitoring server stopped")
