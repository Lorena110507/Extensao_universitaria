import os
import json
import sqlite3
import unittest
from werkzeug.datastructures import MultiDict
from app import (
    app, init_db, DB_PATH, generate_password_hash,
    carregar_produtos, carregar_materiais, carregar_pedidos, USE_SQLITE
)

class TestPedidosGtinScanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("admin-scanner-test-id", "admin", generate_password_hash("admin123"), "Admin", '["Admin"]')
        )
        conn.commit()
        conn.close()

    def test_novo_pedido_com_gtin_query_param(self):
        """Testa abertura do formulário de novo pedido com parâmetro GTIN na URL."""
        materiais = carregar_materiais()
        self.assertTrue(len(materiais) > 0)
        mid = materiais[0]["id"]

        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)

            # Cria bolsa com GTIN específico
            gtin_teste = "7891234567890"
            form_data = MultiDict([
                ("nome", "Bolsa Couro Scanner GTIN"),
                ("emoji", "👜"),
                ("preco_venda", "220,00"),
                ("gtin", gtin_teste),
                ("estoque_pronto", "2"),
                ("material_id[]", mid),
                ("material_qtd[]", "1.0")
            ])
            c.post("/produtos/novo", data=form_data, follow_redirects=True)

            produtos = carregar_produtos()
            prod_criado = next((p for p in produtos if p["nome"] == "Bolsa Couro Scanner GTIN"), None)
            self.assertIsNotNone(prod_criado)
            self.assertEqual(prod_criado["gtin"], gtin_teste)

            # Acessa a rota de novo pedido passando ?gtin=
            resp = c.get(f"/pedidos/novo?gtin={gtin_teste}")
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode("utf-8")
            self.assertIn("inp-gtin-pedido", html)
            self.assertIn("processarGtin", html)
            self.assertIn(gtin_teste, html)
            self.assertIn("Bolsa Couro Scanner GTIN", html)

            # Submete o pedido da bolsa identificada
            resp_post = c.post("/pedidos/novo", data={
                "cliente": "Cliente GTIN Teste",
                "produto_id": prod_criado["id"],
                "quantidade": "1",
                "observacoes": "Adicionado via leitor de código de barras"
            }, follow_redirects=True)
            self.assertEqual(resp_post.status_code, 200)

            pedidos = carregar_pedidos()
            ped = next((p for p in pedidos if p["cliente"] == "Cliente GTIN Teste"), None)
            self.assertIsNotNone(ped)
            self.assertEqual(ped["produto_nome"], "Bolsa Couro Scanner GTIN")
            self.assertEqual(ped["status"], "Concluído")  # havia 2 prontas em estoque

    def test_pedidos_list_possui_botao_leitor(self):
        """Verifica se a tela de pedidos possui o botão de atalho para leitura com leitor de código."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
            resp = c.get("/pedidos")
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode("utf-8")
            self.assertIn("Ler Código da Bolsa", html)
            self.assertIn("abrirScanner", html)

if __name__ == '__main__':
    unittest.main()
