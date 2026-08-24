import os
import json
import sqlite3
import unittest
from werkzeug.datastructures import MultiDict
from app import (
    app, init_db, DB_PATH, generate_password_hash,
    carregar_produtos, carregar_materiais, carregar_pedidos, USE_SQLITE
)

class TestProdutosGtinEstoquePronto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("admin-id-gtin-test", "admin", generate_password_hash("admin123"), "Admin", '["Admin"]')
        )
        conn.commit()
        conn.close()

    def test_produto_criacao_com_gtin_e_estoque_pronto(self):
        """Verifica se produto pode ser criado com GTIN e estoque inicial de peças prontas."""
        materiais = carregar_materiais()
        self.assertTrue(len(materiais) > 0, "Deve haver materiais para a receita do produto")
        mid = materiais[0]["id"]

        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
            
            form_data = MultiDict([
                ("nome", "Bolsa Tote Teste Scanner"),
                ("emoji", "👜"),
                ("preco_venda", "150,00"),
                ("gtin", "7899988776655"),
                ("estoque_pronto", "3"),
                ("material_id[]", mid),
                ("material_qtd[]", "1.0")
            ])
            resp = c.post("/produtos/novo", data=form_data, follow_redirects=True)
            
            self.assertEqual(resp.status_code, 200)
            produtos = carregar_produtos()
            p = next((prod for prod in produtos if prod["nome"] == "Bolsa Tote Teste Scanner"), None)
            self.assertIsNotNone(p)
            self.assertEqual(p["gtin"], "7899988776655")
            self.assertEqual(p["estoque_pronto"], 3)

    def test_ajuste_manual_estoque_pronto(self):
        """Testa adição e remoção manual de peças prontas na aba de produtos."""
        produtos = carregar_produtos()
        p = produtos[0]
        est_inicial = int(p.get("estoque_pronto") or 0)

        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
            
            # Adiciona 2 peças
            resp = c.post(f"/produtos/{p['id']}/ajuste_estoque", data={
                "acao": "adicionar",
                "quantidade": "2",
                "motivo": "Costura antecipada"
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            
            p_atual = next(prod for prod in carregar_produtos() if prod["id"] == p["id"])
            self.assertEqual(p_atual["estoque_pronto"], est_inicial + 2)

    def test_cancelamento_pedido_armazena_bolsa_no_estoque(self):
        """Testa se o cancelamento de um pedido em produção/concluído devolve a bolsa pronta ao estoque de pronta-entrega."""
        produtos = carregar_produtos()
        p = produtos[0]
        est_antes = int(p.get("estoque_pronto") or 0)

        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
            
            # Remove estoque pronto atual para testar pedido sob encomenda
            if est_antes > 0:
                c.post(f"/produtos/{p['id']}/ajuste_estoque", data={"acao": "remover", "quantidade": str(est_antes)})
            
            resp_ped = c.post("/pedidos/novo", data={
                "cliente": "Cliente Cancelamento Teste",
                "produto_id": p["id"],
                "quantidade": "1",
                "observacoes": "Teste de cancelamento"
            }, follow_redirects=True)
            self.assertEqual(resp_ped.status_code, 200)
            
            pedidos = carregar_pedidos()
            ped = next((ped for ped in pedidos if ped["cliente"] == "Cliente Cancelamento Teste"), None)
            self.assertIsNotNone(ped)
            self.assertEqual(ped["status"], "Pendente")
            
            # Move para Em produção (dá baixa nos materiais)
            c.post(f"/pedidos/{ped['id']}/status", data={"status": "Em produção"}, follow_redirects=True)
            
            ped_prod = next(ped for ped in carregar_pedidos() if ped["id"] == ped["id"])
            self.assertTrue(ped_prod["materiais_baixados"])
            
            # Agora cancela o pedido
            resp_canc = c.post(f"/pedidos/{ped['id']}/status", data={"status": "Cancelado"}, follow_redirects=True)
            self.assertEqual(resp_canc.status_code, 200)
            self.assertIn("guardada no estoque".encode("utf-8"), resp_canc.data)
            
            # Verifica que o estoque_pronto do produto aumentou em 1
            p_final = next(prod for prod in carregar_produtos() if prod["id"] == p["id"])
            self.assertEqual(p_final["estoque_pronto"], 1)

if __name__ == '__main__':
    unittest.main()
