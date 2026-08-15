import unittest
from app import app, init_db, generate_password_hash, sqlite3, DB_PATH, carregar_relatorios_customizados


class TestRelatoriosCRUD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("DELETE FROM relatorios_customizados")

        # Admin with full permissions
        cur.execute(
            "INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("admin-rel-id", "admin_rel", generate_password_hash("pass123"), "Admin")
        )

        # Viewer role with only 'read' permission
        cur.execute("INSERT OR IGNORE INTO roles (id, name, description, is_system, created_at) VALUES ('viewer-role', 'ApenasLeitor', 'Leitor', 0, datetime('now'))")
        cur.execute("DELETE FROM role_permissions WHERE role='ApenasLeitor'")
        cur.execute("INSERT INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete) VALUES ('ApenasLeitor', 'relatorios', 0, 1, 0, 0)")
        cur.execute(
            "INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("reader-rel-id", "reader_rel", generate_password_hash("pass123"), "ApenasLeitor")
        )

        conn.commit()
        conn.close()

    def test_create_and_view_custom_report(self):
        with app.test_client() as c:
            # Login as admin
            c.post('/login', data={'username': 'admin_rel', 'password': 'pass123'}, follow_redirects=True)

            # Access creation form
            r_get = c.get('/relatorios/novo')
            self.assertEqual(r_get.status_code, 200)

            # Create new report
            r_post = c.post('/relatorios/novo', data={
                'titulo': 'Relatório Couros Críticos',
                'tipo': 'estoque',
                'tipo_grafico': 'doughnut',
                'categoria_filtro': 'Courino',
                'apenas_criticos': '1',
                'observacoes': 'Acompanhamento semanal de insumos'
            }, follow_redirects=False)

            self.assertEqual(r_post.status_code, 302)
            new_url = r_post.headers['Location']
            self.assertIn('/relatorios/', new_url)

            # View the created report
            r_view = c.get(new_url)
            self.assertEqual(r_view.status_code, 200)
            self.assertIn('Relatório Couros Críticos', r_view.get_data(as_text=True))
            self.assertIn('doughnut', r_view.get_data(as_text=True))

    def test_edit_custom_report(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_rel', 'password': 'pass123'}, follow_redirects=True)

            # Create
            c.post('/relatorios/novo', data={
                'titulo': 'Relatório Financeiro Inicial',
                'tipo': 'financeiro',
                'tipo_grafico': 'bar'
            }, follow_redirects=True)

            rels = carregar_relatorios_customizados()
            self.assertEqual(len(rels), 1)
            rel_id = rels[0]['id']

            # Edit
            r_edit = c.post(f'/relatorios/{rel_id}/editar', data={
                'titulo': 'Relatório Financeiro Atualizado',
                'tipo': 'financeiro',
                'tipo_grafico': 'pie',
                'observacoes': 'Modificado com sucesso'
            }, follow_redirects=True)

            self.assertEqual(r_edit.status_code, 200)
            self.assertIn('Relatório Financeiro Atualizado', r_edit.get_data(as_text=True))
            self.assertIn('pie', r_edit.get_data(as_text=True))

    def test_delete_custom_report(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_rel', 'password': 'pass123'}, follow_redirects=True)

            c.post('/relatorios/novo', data={
                'titulo': 'Relatório Para Excluir',
                'tipo': 'pedidos',
                'tipo_grafico': 'bar'
            }, follow_redirects=True)

            rels = carregar_relatorios_customizados()
            self.assertEqual(len(rels), 1)
            rel_id = rels[0]['id']

            # Delete
            r_del = c.post(f'/relatorios/{rel_id}/excluir', follow_redirects=True)
            self.assertEqual(r_del.status_code, 200)
            self.assertEqual(len(carregar_relatorios_customizados()), 0)

    def test_rbac_permission_restrictions(self):
        with app.test_client() as c:
            # Login as reader (only has 'read' permission on relatorios)
            c.post('/login', data={'username': 'reader_rel', 'password': 'pass123'}, follow_redirects=True)

            # Can view alertas/dashboard
            r_alertas = c.get('/alertas')
            self.assertEqual(r_alertas.status_code, 200)

            # Cannot create report (redirects with access denied flash message)
            r_create = c.get('/relatorios/novo', follow_redirects=True)
            self.assertEqual(r_create.status_code, 200)
            self.assertIn('Acesso negado', r_create.get_data(as_text=True))

            # Post create forbidden
            r_post_create = c.post('/relatorios/novo', data={'titulo': 'Hack', 'tipo': 'estoque', 'tipo_grafico': 'bar'}, follow_redirects=True)
            self.assertEqual(r_post_create.status_code, 200)
            self.assertIn('Acesso negado', r_post_create.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
