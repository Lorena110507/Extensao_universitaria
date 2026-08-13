import sqlite3
from app import app, DB_PATH

app.testing = True

with app.test_client() as client:
    # Login as default admin (password defaults to 'admin' unless ADMIN_PASSWORD env was set before import)
    rv = client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
    print('login status', rv.status_code)
    assert rv.status_code in (200, 302)

    # Ensure /usuarios page loads
    rv = client.get('/usuarios')
    assert rv.status_code == 200
    assert b'Usu' in rv.data  # crude check for Portuguese UI

    # Create a new user
    rv = client.post('/usuarios/novo', data={'username': 'tester', 'password': 'secret', 'password2': 'secret'}, follow_redirects=True)
    print('/usuarios/novo ->', rv.status_code)
    assert rv.status_code == 200

    # Verify user exists in DB
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM usuarios WHERE username=?", ('tester',))
    row = cur.fetchone()
    conn.close()
    assert row is not None, 'User tester not found in DB'
    uid = row[0]
    print('created user id', uid)

    # Delete the user
    rv = client.post(f'/usuarios/{uid}/excluir', follow_redirects=True)
    print('/usuarios/<id>/excluir ->', rv.status_code)
    assert rv.status_code == 200

    # Confirm deletion
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE username=?", ('tester',))
    row = cur.fetchone()
    conn.close()
    assert row is None, 'User tester still present after delete'

print('TESTS OK')
