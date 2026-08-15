import unittest
import sqlite3
from app import app, DB_PATH, init_db, generate_password_hash


class TestAuthorization(unittest.TestCase):
    def setUp(self):
        app.testing = True
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        users = [
            ('admin-id', 'admin', generate_password_hash('adminpass'), 'Admin'),
            ('fin-id', 'fin', generate_password_hash('finpass'), 'Financeiro'),
            ('est-id', 'est', generate_password_hash('estpass'), 'Estoque'),
            ('sales-id', 'sales', generate_password_hash('salespass'), 'Vendas'),
        ]
        for uid, username, pwd, role in users:
            cur.execute("INSERT INTO usuarios (id,username,password_hash,role,created_at) VALUES (?,?,?,?,datetime('now'))", (uid, username, pwd, role))
        conn.commit()
        conn.close()

    def test_authorization_matrix(self):
        with app.test_client() as c:
            def login(user, pw):
                return c.post('/login', data={'username': user, 'password': pw}, follow_redirects=True)

            # admin should access /usuarios
            r = login('admin', 'adminpass')
            self.assertEqual(r.status_code, 200)
            r = c.get('/usuarios')
            self.assertEqual(r.status_code, 200)

            # financeiro can access /financeiro but not /usuarios
            r = login('fin', 'finpass')
            self.assertEqual(r.status_code, 200)
            r = c.get('/financeiro')
            self.assertEqual(r.status_code, 200)
            r = c.get('/usuarios', follow_redirects=False)
            self.assertEqual(r.status_code, 302)

            # estoque can access adicionar
            r = login('est', 'estpass')
            self.assertEqual(r.status_code, 200)
            r = c.get('/adicionar')
            self.assertEqual(r.status_code, 200)


if __name__ == '__main__':
    unittest.main()
