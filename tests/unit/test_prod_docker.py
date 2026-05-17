import pathlib


def test_nginx_conf_exists():
    path = pathlib.Path(__file__).parents[2] / "infra/nginx/nginx.conf"
    assert path.exists()


def test_nginx_conf_has_websocket_upgrade():
    path = pathlib.Path(__file__).parents[2] / "infra/nginx/nginx.conf"
    content = path.read_text()
    assert "Upgrade" in content
    assert "upgrade" in content


def test_nginx_conf_has_spa_fallback():
    path = pathlib.Path(__file__).parents[2] / "infra/nginx/nginx.conf"
    content = path.read_text()
    assert "try_files" in content
    assert "/index.html" in content


def test_docker_compose_prod_exists():
    path = pathlib.Path(__file__).parents[2] / "infra/docker-compose.prod.yml"
    assert path.exists()


def test_docker_compose_prod_has_nginx():
    import yaml
    path = pathlib.Path(__file__).parents[2] / "infra/docker-compose.prod.yml"
    data = yaml.safe_load(path.read_text())
    assert "nginx" in data["services"]
    assert "api" in data["services"]
    assert "temporal-worker" in data["services"]


def test_gunicorn_conf_exists():
    path = pathlib.Path(__file__).parents[2] / "backend/gunicorn.conf.py"
    assert path.exists()


def test_gunicorn_conf_uses_uvicorn_worker():
    path = pathlib.Path(__file__).parents[2] / "backend/gunicorn.conf.py"
    content = path.read_text()
    assert "UvicornWorker" in content
