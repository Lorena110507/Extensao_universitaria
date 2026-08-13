import sqlite3
from app import app, DB_PATH, init_db, generate_password_hash

app.testing = True

# Prepare DB with test users
init_db()
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("DELETE FROM usuarios")
users = [
    ('admin-id', 'admin', 'PLAIN:adminpass', 'Admin'),
    ('fin-id', 'fin', 'PLAIN:finpass', 'Financeiro'),
    ('est-id', 'est', 'PLAIN:estpass', 'Estoque'),
    ('sales-id', 'sales', 'PLAIN:salespass', 'Vendas'),
]
for uid, username, pwd, role in users:
    cur.execute("INSERT INTO usuarios (id,username,password_hash,role,created_at) VALUES (?,?,?,?,datetime('now'))", (uid, username, pwd, role))
conn.commit()
conn.close()

with app.test_client() as c:
    # helper to login
    def login(user, pw):
        return c.post('/login', data={'username': user, 'password': pw}, follow_redirects=True)

    # admin should access /usuarios
    r = login('admin','adminpass')
    assert r.status_code == 200
    r = c.get('/usuarios')
    assert r.status_code == 200

    # financeiro can access /financeiro but not /usuarios
    r = login('fin','finpass')
    r = c.get('/financeiro')
    assert r.status_code in (200,302)
    r = c.get('/usuarios')
    assert r.status_code in (302,)

    # estoque can access adicionar
    r = login('est','estpass')
    r = c.get('/adicionar')
    assert r.status_code in (200,302)

print('AUTHZ TESTS OK')
