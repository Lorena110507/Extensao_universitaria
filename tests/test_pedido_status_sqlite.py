import unittest
import json
import sqlite3
import uuid
from datetime import datetime
from app import app, init_db, generate_password_hash, DB_PATH, carregar_materiais, carregar_movimentacoes


class TestPedidoStatusSQLite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("DELETE FROM pedidos")
        cur.execute("DELETE FROM produtos")
        cur.execute("DELETE FROM materiais")
        cur.execute("DELETE FROM movimentacoes")
        cur.execute("DELETE FROM sobras")

        # Admin user
        cur.execute(
            "INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("admin-status-id", "admin_status", generate_password_hash("pass123"), "Admin")
        )

        # Materials
        now = datetime.now().isoformat()
        cur.execute(
            "INSERT INTO materiais (id, nome, categoria, emoji, quantidade, unidade, quantidade_minima, custo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("mat-couro-1", "Couro Legítimo Preto", "Couro", "⬛", 10.0, "metros", 2.0, 50.0, now, now)
        )
        cur.execute(
            "INSERT INTO materiais (id, nome, categoria, emoji, quantidade, unidade, quantidade_minima, custo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("mat-ziper-1", "Zíper Reforçado 30cm", "Metais", "🤐", 20.0, "unidades", 5.0, 3.5, now, now)
        )

        # Product "Bolsa Tote Clássica" requiring 1.5m couro and 1 ziper
        receita = [
            {"material_id": "mat-couro-1", "quantidade": 1.5},
            {"material_id": "mat-ziper-1", "quantidade": 1.0}
        ]
        cur.execute(
            "INSERT INTO produtos (id, nome, emoji, preco_venda, receita, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("prod-bolsa-1", "Bolsa Tote Clássica", "👜", 180.0, json.dumps(receita), now, now)
        )

        # Order for 2 bolsas
        cur.execute(
            "INSERT INTO pedidos (id, cliente, produto_id, produto_nome, produto_emoji, quantidade, preco_unitario, valor_total, status, materiais_baixados, data_pedido, data_pedido_iso, observacoes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ped-bolsa-1", "Mariana Silva", "prod-bolsa-1", "Bolsa Tote Clássica", "👜",
                2, 180.0, 360.0, "Pendente", 0, "14/08/2026", now, "Cliente VIP", now, now
            )
        )

        # Sobra
        cur.execute(
            "INSERT INTO sobras (id, material_id, descricao, quantidade, unidade, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("sobra-1", "mat-couro-1", "Retalho de Couro Preto", 2.0, "metros", "14/08/2026", "Disponível", now, now)
        )

        conn.commit()
        conn.close()

    def test_update_status_deducts_recipe_materials_without_sqlite_lock(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_status', 'password': 'pass123'}, follow_redirects=True)

            # Change order status from 'Pendente' to 'Em produção'
            r = c.post('/pedidos/ped-bolsa-1/status', data={'status': 'Em produção'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIn('atualizado para', r.get_data(as_text=True))
            self.assertIn('Em produção', r.get_data(as_text=True))

            # Verify SQLite DB state
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Check order status
            cur.execute("SELECT status, materiais_baixados FROM pedidos WHERE id='ped-bolsa-1'")
            ped = cur.fetchone()
            self.assertEqual(ped["status"], "Em produção")
            self.assertEqual(ped["materiais_baixados"], 1)

            # Check material deductions:
            # 10.0 couro - (1.5 * 2) = 7.0
            cur.execute("SELECT quantidade FROM materiais WHERE id='mat-couro-1'")
            self.assertAlmostEqual(cur.fetchone()[0], 7.0)

            # 20.0 ziper - (1.0 * 2) = 18.0
            cur.execute("SELECT quantidade FROM materiais WHERE id='mat-ziper-1'")
            self.assertAlmostEqual(cur.fetchone()[0], 18.0)

            # Check movimentacoes
            cur.execute("SELECT * FROM movimentacoes WHERE tipo='producao'")
            movs = cur.fetchall()
            self.assertEqual(len(movs), 2)
            conn.close()

            # Move to 'Concluído' and then 'Entregue' (materials should NOT be deducted again)
            r2 = c.post('/pedidos/ped-bolsa-1/status', data={'status': 'Concluído'}, follow_redirects=True)
            self.assertEqual(r2.status_code, 200)

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT quantidade FROM materiais WHERE id='mat-couro-1'")
            self.assertAlmostEqual(cur.fetchone()[0], 7.0) # still 7.0
            conn.close()

    def test_insufficient_stock_rollback(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_status', 'password': 'pass123'}, follow_redirects=True)

            # Reduce material stock to 0.5m (less than required 3.0m)
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE materiais SET quantidade=0.5 WHERE id='mat-couro-1'")
            conn.commit()
            conn.close()

            # Attempt to change order to 'Em produção'
            r = c.post('/pedidos/ped-bolsa-1/status', data={'status': 'Em produção'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIn('estoque insuficiente', r.get_data(as_text=True))

            # Verify order is still 'Pendente' and materials were not deducted
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT status, materiais_baixados FROM pedidos WHERE id='ped-bolsa-1'")
            row = cur.fetchone()
            self.assertEqual(row[0], "Pendente")
            self.assertEqual(row[1], 0)

            cur.execute("SELECT quantidade FROM materiais WHERE id='mat-couro-1'")
            self.assertAlmostEqual(cur.fetchone()[0], 0.5)
            conn.close()

    def test_status_cancelado(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_status', 'password': 'pass123'}, follow_redirects=True)

            r = c.post('/pedidos/ped-bolsa-1/status', data={'status': 'Cancelado'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT status, materiais_baixados FROM pedidos WHERE id='ped-bolsa-1'")
            row = cur.fetchone()
            self.assertEqual(row[0], "Cancelado")
            self.assertEqual(row[1], 0)
            conn.close()

    def test_sobra_reaproveitar_without_sqlite_lock(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin_status', 'password': 'pass123'}, follow_redirects=True)

            # Reaproveitar sobra (should add 2.0m back to mat-couro-1)
            r = c.post('/sobras/sobra-1/reaproveitar', follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIn('reaproveitada com sucesso', r.get_data(as_text=True))

            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT quantidade FROM materiais WHERE id='mat-couro-1'")
            # 10.0 + 2.0 = 12.0
            self.assertAlmostEqual(cur.fetchone()[0], 12.0)

            cur.execute("SELECT status FROM sobras WHERE id='sobra-1'")
            self.assertEqual(cur.fetchone()[0], "Reaproveitado")
            conn.close()


if __name__ == '__main__':
    unittest.main()
