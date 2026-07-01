workers = 3
threads = 2
timeout = 60
preload_app = True  # carga la app una vez en el master (migrations corren 1 sola vez)

def post_fork(server, worker):
    # Después de fork, cada worker debe tener su propio pool de conexiones
    from main import db
    db.engine.dispose()
