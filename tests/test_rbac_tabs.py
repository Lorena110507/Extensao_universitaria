import unittest
import sqlite3
import uuid
from app import app, DB_PATH, init_db, carregar_papeis, encontrar_papel, user_has_permission, user_can_access_tab, SYSTEM_TABS, generate_password_hash


class TestRBACTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("DELETE FROM roles WHERE is_system=0")

        # Seed test admin and test user
        now = "2026-08-14T20:00:00"
        cur.execute("INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("admin-test-id", "admin_tester", generate_password_hash("pass123"), "Admin", now))
        cur.execute("INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("stock-test-id", "estoquista", generate_password_hash("pass123"), "Estoque", now))
        conn.commit()
        conn.close()

    def test_default_roles_seeded(self):
        papeis = carregar_papeis()
        role_names = [p["name"] for p in papeis]
        self.assertIn("Admin", role_names)
        self.assertIn("Estoque", role_names)
        self.assertIn("Vendas", role_names)
        self.assertIn("Producao", role_names)
        self.assertIn("Financeiro", role_names)
        self.assertIn("Relatorios", role_names)

    def test_create_and_delete_custom_role(self):
        with app.test_client() as c:
            # Login as admin
            r = c.post('/login', data={'username': 'admin_tester', 'password': 'pass123'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            # Create custom role "Almoxarife" with only estoque and baixa
            r = c.post('/roles/novo', data={
                'name': 'Almoxarife',
                'description': 'Apenas confere estoque e dá baixa',
                'can_read_estoque': '1',
                'can_update_estoque': '1',
                'can_create_baixa': '1',
            }, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            role_obj = encontrar_papel('Almoxarife')
            self.assertIsNotNone(role_obj)
            self.assertTrue(role_obj['permissions']['estoque']['can_read'])
            self.assertTrue(role_obj['permissions']['estoque']['can_update'])
            self.assertTrue(role_obj['permissions']['baixa']['can_create'])
            # Financeiro should be disabled
            self.assertFalse(role_obj['permissions'].get('financeiro', {}).get('can_read', False))

            # Delete custom role
            r = c.post('/roles/Almoxarife/excluir', follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIsNone(encontrar_papel('Almoxarife'))

    def test_admin_role_cannot_be_deleted(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_tester', 'password': 'pass123'}, follow_redirects=True)
            r = c.post('/roles/Admin/excluir', follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIsNotNone(encontrar_papel('Admin'))

    def test_role_based_tab_access(self):
        with app.test_client() as c:
            # Create a user with Almoxarife role
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO roles (id, name, description, is_system, created_at, updated_at) VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))",
                        ("alm-id", "Almoxarife", "Apenas estoque",))
            cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete, updated_at) VALUES (?, 'estoque', 0, 1, 1, 0, datetime('now'))", ("Almoxarife",))
            cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete, updated_at) VALUES (?, 'baixa', 1, 1, 0, 0, datetime('now'))", ("Almoxarife",))
            cur.execute("INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, 'Almoxarife', datetime('now'))",
                        ("user-alm-id", "joao_almoxarife", generate_password_hash("pass123")))
            conn.commit()
            conn.close()

            # Login as joao_almoxarife
            c.post('/login', data={'username': 'joao_almoxarife', 'password': 'pass123'}, follow_redirects=True)

            # Permitted routes
            r = c.get('/estoque')
            self.assertEqual(r.status_code, 200)
            r = c.get('/baixa')
            self.assertEqual(r.status_code, 200)

            # Denied routes (redirect to home)
            r = c.get('/financeiro', follow_redirects=False)
            self.assertEqual(r.status_code, 302)
            r = c.get('/usuarios', follow_redirects=False)
            self.assertEqual(r.status_code, 302)
            r = c.get('/roles', follow_redirects=False)
            self.assertEqual(r.status_code, 302)

            # Check rendered HTML in home has only permitted tabs in drawer
            r = c.get('/')
            self.assertEqual(r.status_code, 200)
            self.assertIn(b'Estoque', r.data)
            self.assertIn(b'Dar Baixa', r.data)
            self.assertNotIn(b'href="/financeiro"', r.data)
            self.assertNotIn(b'href="/usuarios"', r.data)
            self.assertNotIn(b'href="/roles"', r.data)


if __name__ == '__main__':
    unittest.main()
