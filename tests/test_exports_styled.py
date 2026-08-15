import io
import unittest
import openpyxl
from app import app, init_db, generate_password_hash, sqlite3, DB_PATH


class TestExportsStyled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute(
            "INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("admin-export-id", "admin_exporter", generate_password_hash("pass123"), "Admin")
        )
        # Ensure some sample material and order
        cur.execute("INSERT OR IGNORE INTO materiais (id, nome, categoria, emoji, quantidade, unidade, quantidade_minima, custo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    ("mat-exp-1", "Couro Marrom", "Courino", "🟫", 15.0, "metros", 5.0, 45.0))
        cur.execute("INSERT OR IGNORE INTO despesas (id, descricao, valor, categoria, data, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    ("desp-exp-1", "Linhas e Agulhas", 120.0, "Material", "14/08/2026"))
        conn.commit()
        conn.close()

    def test_pdf_export_styled(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_exporter', 'password': 'pass123'}, follow_redirects=True)
            r = c.get('/exportar/pdf')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.content_type, 'application/pdf')
            self.assertTrue(r.data.startswith(b'%PDF'))
            self.assertGreater(len(r.data), 2000)

    def test_excel_export_styled_tables(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_exporter', 'password': 'pass123'}, follow_redirects=True)
            r = c.get('/exportar/xlsx')
            self.assertEqual(r.status_code, 200)
            self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', r.content_type)
            self.assertGreater(len(r.data), 5000)

            # Load the exported Excel workbook with openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(r.data))
            sheet_names = wb.sheetnames
            self.assertIn("Resumo Geral", sheet_names)
            self.assertIn("Estoque de Materiais", sheet_names)
            self.assertIn("Pedidos", sheet_names)
            self.assertIn("Despesas", sheet_names)

            # Verify table exists in Estoque sheet
            ws_mat = wb["Estoque de Materiais"]
            self.assertIn("TabelaEstoque", ws_mat.tables)
            self.assertEqual(ws_mat.tables["TabelaEstoque"].tableStyleInfo.name, "TableStyleMedium9")

            # Verify Resumo Geral content
            ws_resumo = wb["Resumo Geral"]
            self.assertIn("ATELIÊ HAITI", ws_resumo["A1"].value)


if __name__ == '__main__':
    unittest.main()
