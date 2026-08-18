"""
ania_assistant.py - Motor Inteligente Completo da Assistente Virtual Ania
Ateliê Haiti - 100% Gratuito (Zero dependências pagas)
Execução completa de TODAS as ações do site por voz e digitação com validação rigorosa de RBAC.
"""

import re
import unicodedata
import uuid
import json
import sqlite3
from datetime import datetime


def remover_acentos(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()


def formatar_moeda(val: float) -> str:
    try:
        val = float(val or 0)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


class AniaAssistant:
    def __init__(self, app_context):
        self.app = app_context

    def processar_mensagem(self, prompt: str, user: dict) -> dict:
        """
        Processador central de linguagem natural e despachante de ações.
        Analisa intenções, extrai entidades, valida permissões RBAC e executa no sistema.
        """
        if not prompt or not prompt.strip():
            return {
                "reply": "Olá! Estou ouvindo. Como posso te ajudar hoje no ateliê?",
                "voice_text": "Olá! Estou ouvindo. Como posso te ajudar hoje no ateliê?",
                "suggestions": ["📄 Enviar relatório em PDF", "📦 Consultar estoque", "🧾 Pedidos pendentes", "💰 Resumo financeiro"],
            }

        prompt_orig = prompt.strip()
        p_clean = remover_acentos(prompt_orig)
        user_nome = user.get("nome") or user.get("username") or "Artesã(o)"
        roles = self.app.usuario_roles_lista(user)
        roles_str = ", ".join(roles) if roles else "Colaborador"

        # ── 1. SAUDAÇÃO & MENU DE AJUDA ────────────────────────────────────────
        if any(w in p_clean for w in ["quem e voce", "o que voce faz", "ajuda", "comandos", "menu", "o que posso pedir"]) or p_clean in ["ola", "oi", "bom dia", "boa tarde", "boa noite", "ania"]:
            return self._responder_ajuda(user_nome, roles)

        # ── 2. CONSULTAR PERMISSÕES / MEU PERFIL ──────────────────────────────
        if any(w in p_clean for w in ["minhas permissoes", "meu perfil", "meu papel", "o que posso fazer", "meus acessos", "minha conta"]):
            return self._responder_minhas_permissoes(user, user_nome, roles)

        # ── 3. RELATÓRIOS & EXPORTAÇÕES (PDF, EXCEL, JSON) ───────────────────
        if any(w in p_clean for w in ["relatorio em pdf", "enviar relatorio", "gerar pdf", "baixar pdf", "exportar pdf", "pdf do financeiro", "relatorio financeiro pdf"]):
            if not self._tem_permissao(user, "relatorios", "read"):
                return self._resposta_negada(user_nome, roles_str, "relatorios", "read", "gerar e baixar relatórios em PDF")
            return self._gerar_relatorio_pdf()

        if any(w in p_clean for w in ["exportar excel", "baixar excel", "gerar excel", "planilha excel", "exportar xlsx", "baixar xlsx"]):
            if not self._tem_permissao(user, "relatorios", "read"):
                return self._resposta_negada(user_nome, roles_str, "relatorios", "read", "exportar planilhas Excel")
            return self._gerar_exportacao_excel()

        if any(w in p_clean for w in ["backup", "exportar tudo", "exportar json", "backup completo"]):
            if not self._tem_permissao(user, "relatorios", "read"):
                return self._resposta_negada(user_nome, roles_str, "relatorios", "read", "fazer backup completo dos dados")
            return self._gerar_backup_json()

        # ── 4. AÇÕES DE PEDIDOS ───────────────────────────────────────────────
        # Mudar status do pedido (Pendente, Em Produção, Concluído, Entregue, Cancelado)
        if any(w in p_clean for w in ["mudar status", "alterar status", "concluir pedido", "cancelar pedido", "entregar pedido", "mover para producao", "colocar em producao"]):
            if not self._tem_permissao(user, "pedidos", "update"):
                return self._resposta_negada(user_nome, roles_str, "pedidos", "update", "atualizar o status de pedidos")
            return self._executar_mudar_status_pedido(p_clean, prompt_orig, user)

        # Excluir pedido
        if any(w in p_clean for w in ["excluir pedido", "remover pedido", "apagar pedido", "deletar pedido"]):
            if not self._tem_permissao(user, "pedidos", "delete"):
                return self._resposta_negada(user_nome, roles_str, "pedidos", "delete", "excluir pedidos")
            return self._executar_excluir_pedido(p_clean, prompt_orig)

        # Criar novo pedido
        if any(w in p_clean for w in ["criar pedido", "novo pedido", "adicionar pedido", "fazer pedido", "registrar pedido"]):
            if not self._tem_permissao(user, "pedidos", "create"):
                return self._resposta_negada(user_nome, roles_str, "pedidos", "create", "criar novos pedidos de clientes")
            return self._executar_criar_pedido(p_clean, prompt_orig, user)

        # ── 5. AÇÕES DE ESTOQUE (CADASTRAR, ENTRADA, BAIXA, EXCLUIR) ──────────
        # Cadastrar novo material (se tiver nome/detalhes)
        if any(w in p_clean for w in ["cadastrar material", "adicionar material", "novo material", "criar material", "adicionar novo insumo"]):
            if not self._tem_permissao(user, "adicionar", "create"):
                return self._resposta_negada(user_nome, roles_str, "adicionar", "create", "cadastrar novos materiais")
            return self._executar_cadastrar_material(p_clean, prompt_orig)

        # Entrada de material (adicionar quantidade a material existente)
        if any(w in p_clean for w in ["dar entrada", "entrada de material", "adicionar ao estoque de", "chegou mais", "repor estoque de", "aumentar estoque"]):
            if not self._tem_permissao(user, "estoque", "update"):
                return self._resposta_negada(user_nome, roles_str, "estoque", "update", "dar entrada de estoque")
            return self._executar_dar_entrada_material(p_clean, prompt_orig, user)

        # Dar baixa de material
        if any(p_clean.startswith(w) for w in ["dar baixa", "baixar", "usei", "consumi", "gastei", "retirar do estoque"]) or "dar baixa" in p_clean:
            if not self._tem_permissao(user, "baixa", "create"):
                return self._resposta_negada(user_nome, roles_str, "baixa", "create", "dar baixa de insumos no estoque")
            return self._executar_dar_baixa(p_clean, prompt_orig, user)

        # Excluir material
        if any(w in p_clean for w in ["excluir material", "remover material", "apagar material", "deletar material"]):
            if not self._tem_permissao(user, "estoque", "delete"):
                return self._resposta_negada(user_nome, roles_str, "estoque", "delete", "excluir materiais do estoque")
            return self._executar_excluir_material(p_clean, prompt_orig)

        # ── 6. AÇÕES DE PRODUTOS & BOLSAS ─────────────────────────────────────
        # Ajuste de estoque pronto (peças prontas)
        if any(w in p_clean for w in ["ajustar pecas prontas", "adicionar pecas prontas", "adicionar bolsa pronta", "remover peca pronta", "ajustar estoque pronto"]) or (("pecas prontas" in p_clean or "peca pronta" in p_clean or "estoque pronto" in p_clean) and any(w in p_clean for w in ["adicionar", "remover", "ajustar", "colocar", "tirar"])):
            if not self._tem_permissao(user, "produtos", "update"):
                return self._resposta_negada(user_nome, roles_str, "produtos", "update", "ajustar o estoque de peças prontas")
            return self._executar_ajuste_estoque_pronto(p_clean, prompt_orig, user)

        # Cadastrar produto / bolsa
        if any(w in p_clean for w in ["cadastrar produto", "cadastrar bolsa", "nova bolsa", "novo produto", "criar bolsa", "criar produto"]):
            if not self._tem_permissao(user, "produtos", "create"):
                return self._resposta_negada(user_nome, roles_str, "produtos", "create", "cadastrar novas bolsas e produtos")
            return self._executar_cadastrar_produto(p_clean, prompt_orig)

        # Excluir produto
        if any(w in p_clean for w in ["excluir produto", "excluir bolsa", "remover produto", "remover bolsa"]):
            if not self._tem_permissao(user, "produtos", "delete"):
                return self._resposta_negada(user_nome, roles_str, "produtos", "delete", "excluir produtos do catálogo")
            return self._executar_excluir_produto(p_clean, prompt_orig)

        # ── 7. AÇÕES DE SOBRAS & RETALHOS ─────────────────────────────────────
        if any(w in p_clean for w in ["cadastrar sobra", "cadastrar retalho", "adicionar sobra", "nova sobra", "guardar retalho"]):
            if not self._tem_permissao(user, "sobras", "create"):
                return self._resposta_negada(user_nome, roles_str, "sobras", "create", "cadastrar sobras e retalhos")
            return self._executar_cadastrar_sobra(p_clean, prompt_orig)

        if any(w in p_clean for w in ["reaproveitar sobra", "usar sobra", "usar retalho", "descartar sobra", "descartar retalho"]):
            if not self._tem_permissao(user, "sobras", "update"):
                return self._resposta_negada(user_nome, roles_str, "sobras", "update", "atualizar status de sobras")
            return self._executar_acao_sobra(p_clean, prompt_orig)

        if any(w in p_clean for w in ["excluir sobra", "remover sobra", "apagar sobra", "deletar sobra"]):
            if not self._tem_permissao(user, "sobras", "delete"):
                return self._resposta_negada(user_nome, roles_str, "sobras", "delete", "excluir registros de sobras")
            return self._executar_excluir_sobra(p_clean, prompt_orig)

        # ── 8. AÇÕES FINANCEIRAS (DESPESAS) ───────────────────────────────────
        if any(w in p_clean for w in ["cadastrar despesa", "adicionar despesa", "nova despesa", "registrar despesa", "gasto de", "pagamos", "paguei"]):
            if not self._tem_permissao(user, "financeiro", "create"):
                return self._resposta_negada(user_nome, roles_str, "financeiro", "create", "cadastrar despesas no financeiro")
            return self._executar_cadastrar_despesa(p_clean, prompt_orig)

        if any(w in p_clean for w in ["excluir despesa", "remover despesa", "apagar despesa", "deletar despesa"]):
            if not self._tem_permissao(user, "financeiro", "delete"):
                return self._resposta_negada(user_nome, roles_str, "financeiro", "delete", "excluir registros de despesas")
            return self._executar_excluir_despesa(p_clean, prompt_orig)

        # ── 9. AÇÕES DE USUÁRIOS & PAPÉIS ────────────────────────────────────
        if any(w in p_clean for w in ["cadastrar usuario", "criar usuario", "novo usuario"]):
            if not self._tem_permissao(user, "usuarios", "create"):
                return self._resposta_negada(user_nome, roles_str, "usuarios", "create", "criar novos usuários")
            return self._executar_cadastrar_usuario(p_clean, prompt_orig)

        # ── 10. NAVEGAÇÃO RÁPIDA ──────────────────────────────────────────────
        nav_match = self._verificar_navegacao(p_clean)
        if nav_match:
            recurso, url_dest, nome_tela = nav_match
            if not self._tem_permissao(user, recurso, "read") and not self._tem_permissao(user, recurso, "create"):
                return self._resposta_negada(user_nome, roles_str, recurso, "read", f"navegar até a página de {nome_tela}")
            return {
                "reply": f"🧭 Abrindo a tela de **{nome_tela}** para você...",
                "voice_text": f"Abrindo a tela de {nome_tela}.",
                "action": {"type": "navigate", "url": url_dest},
                "suggestions": ["Voltar ao início", "Consultar estoque", "Ver pedidos"],
            }

        # ── 11. CONSULTAS GERAIS E INFORMATIVAS ───────────────────────────────
        # Alertas e diagnóstico
        if any(w in p_clean for w in ["alerta", "alertas", "estoque baixo", "acabando", "abaixo do minimo", "resumo do atelier", "diagnostico"]):
            if not self._tem_permissao(user, "relatorios", "read"):
                return self._resposta_negada(user_nome, roles_str, "relatorios", "read", "visualizar alertas e relatórios de desempenho")
            return self._consultar_alertas_e_resumo()

        # Financeiro
        if any(w in p_clean for w in ["financeiro", "saldo", "faturamento", "receita", "despesa", "lucro", "caixa", "faturamos", "ganhos"]):
            if not self._tem_permissao(user, "financeiro", "read"):
                return self._resposta_negada(user_nome, roles_str, "financeiro", "read", "consultar dados financeiros e faturamento")
            return self._consultar_financeiro(p_clean)

        # Pedidos
        if any(w in p_clean for w in ["pedido", "pedidos", "encomenda", "encomendas"]):
            if not self._tem_permissao(user, "pedidos", "read"):
                return self._resposta_negada(user_nome, roles_str, "pedidos", "read", "visualizar a lista de pedidos de clientes")
            return self._consultar_pedidos(p_clean)

        # Produtos e bolsas
        if any(w in p_clean for w in ["bolsa", "bolsas", "produto", "produtos", "receita da bolsa", "preco da bolsa", "pronta entrega"]):
            if not self._tem_permissao(user, "produtos", "read"):
                return self._resposta_negada(user_nome, roles_str, "produtos", "read", "consultar catálogo de produtos e receitas")
            return self._consultar_produtos(p_clean)

        # Sobras e retalhos
        if any(w in p_clean for w in ["sobra", "sobras", "retalho", "retalhos", "reaproveitamento"]):
            if not self._tem_permissao(user, "sobras", "read"):
                return self._resposta_negada(user_nome, roles_str, "sobras", "read", "consultar sobras e retalhos")
            return self._consultar_sobras()

        # Usuários
        if any(w in p_clean for w in ["usuario", "usuarios", "quem tem acesso", "listar usuarios"]):
            if not self._tem_permissao(user, "usuarios", "read"):
                return self._resposta_negada(user_nome, roles_str, "usuarios", "read", "visualizar usuários do sistema")
            return self._consultar_usuarios()

        # Estoque geral ou específico
        if any(w in p_clean for w in ["estoque", "material", "materiais", "quanto temos", "quantidade de", "insumo", "insumos", "gtin"]) or self._busca_material_direta(p_clean):
            if not self._tem_permissao(user, "estoque", "read"):
                return self._resposta_negada(user_nome, roles_str, "estoque", "read", "consultar materiais e quantidades em estoque")
            return self._consultar_estoque(p_clean, prompt_orig)

        # ── FALLBACK ──────────────────────────────────────────────────────────
        return {
            "reply": f"Entendi sua mensagem, **{user_nome}**. O que exatamente você gostaria que eu faça?",
            "voice_text": "Não compreendi totalmente. Escolha uma das ações abaixo ou reformule sua pergunta.",
            "suggestions": [
                "📄 Enviar relatório em PDF",
                "📦 Consultar estoque",
                "🧾 Criar novo pedido",
                "✂️ Dar baixa de material",
                "💰 Resumo financeiro",
                "📊 Ver alertas",
                "Minhas permissões"
            ],
        }

    # ── HELPERS DE RBAC ──────────────────────────────────────────────────────

    def _tem_permissao(self, user: dict, recurso: str, acao: str) -> bool:
        roles = self.app.usuario_roles_lista(user)
        if "Admin" in roles:
            return True
        return self.app.user_has_permission(recurso, acao)

    def _resposta_negada(self, user_nome: str, roles_str: str, recurso: str, acao: str, acao_desc: str) -> dict:
        nome_amigavel = {
            "estoque": "Estoque de Materiais",
            "adicionar": "Adicionar Material",
            "baixa": "Dar Baixa em Insumos",
            "produtos": "Produtos & Receitas",
            "pedidos": "Pedidos dos Clientes",
            "sobras": "Sobras e Retalhos",
            "financeiro": "Gestão Financeira",
            "relatorios": "Alertas e Relatórios",
            "usuarios": "Gestão de Usuários",
            "roles": "Papéis & Permissões"
        }.get(recurso, recurso.capitalize())

        msg = (
            f"🔒 **Acesso Negado (RBAC)**\n\n"
            f"Desculpe, **{user_nome}**. Seu perfil de acesso (*{roles_str}*) **não possui permissão** para {acao_desc}.\n\n"
            f"📌 **Módulo Necessário**: `{nome_amigavel}` (Permissão `{recurso}:{acao}`).\n"
            f"Caso precise realizar esta operação, solicite a um **Administrador** para ajustar seus papéis em *Papéis & Permissões*."
        )
        voice = f"Acesso negado. Seu perfil não tem permissão para {acao_desc} no módulo de {nome_amigavel}."
        return {
            "success": False,
            "denied": True,
            "reply": msg,
            "voice_text": voice,
            "suggestions": ["Minhas permissões", "O que posso fazer?", "Consultar estoque", "Ver pedidos"]
        }

    # ── 1. RELATÓRIOS E EXPORTAÇÕES (PDF, EXCEL, JSON) ───────────────────────

    def _gerar_relatorio_pdf(self) -> dict:
        pedidos = self.app.carregar_pedidos()
        despesas = self.app.carregar_despesas()
        materiais = self.app.carregar_materiais()

        rec_total = sum(float(p.get("valor_total") or 0) for p in pedidos if p.get("status") in ("Concluído", "Entregue"))
        desp_total = sum(float(d.get("valor") or 0) for d in despesas)
        saldo = rec_total - desp_total

        msg = (
            f"📄 **Relatório Financeiro & Operacional em PDF Gerado!** ✨\n\n"
            f"O relatório completo com layout artesanal e indicadores do Ateliê Haiti está pronto para download:\n\n"
            f"• **Faturamento Realizado**: {formatar_moeda(rec_total)}\n"
            f"• **Despesas Registradas**: {formatar_moeda(desp_total)}\n"
            f"• **Saldo Líquido**: **{formatar_moeda(saldo)}**\n"
            f"• **Total de Pedidos**: {len(pedidos)} | **Materiais**: {len(materiais)}\n\n"
            f"<a href=\"/exportar/pdf\" target=\"_blank\" class=\"btn-primary\" style=\"display:inline-block; padding:10px 18px; font-size:15px !important; text-decoration:none; margin-top:6px;\">📥 Baixar Relatório em PDF</a>"
        )
        voice = f"Relatório financeiro em PDF gerado com sucesso. O faturamento é de {formatar_moeda(rec_total)} e o saldo líquido é de {formatar_moeda(saldo)}. O download foi disponibilizado."
        return {
            "success": True,
            "reply": msg,
            "voice_text": voice,
            "action": {"type": "download", "url": "/exportar/pdf", "filename": "relatorio_atelie_haiti.pdf"},
            "suggestions": ["📊 Ver alertas", "💰 Resumo financeiro", "📦 Consultar estoque"]
        }

    def _gerar_exportacao_excel(self) -> dict:
        msg = (
            f"📊 **Planilha Excel (XLSX) Gerada com Sucesso!**\n\n"
            f"A planilha contém abas completas com formatação profissional de **Estoque, Produtos, Pedidos, Despesas e Sobras**.\n\n"
            f"<a href=\"/exportar/xlsx\" target=\"_blank\" class=\"btn-primary\" style=\"display:inline-block; padding:10px 18px; font-size:15px !important; text-decoration:none; margin-top:6px;\">📥 Baixar Planilha Excel (.xlsx)</a>"
        )
        voice = "Planilha Excel com todas as abas do ateliê gerada com sucesso para download."
        return {
            "success": True,
            "reply": msg,
            "voice_text": voice,
            "action": {"type": "download", "url": "/exportar/xlsx", "filename": "export_atelie_haiti.xlsx"},
            "suggestions": ["📄 Gerar PDF", "💰 Financeiro", "Ver estoque"]
        }

    def _gerar_backup_json(self) -> dict:
        msg = (
            f"💾 **Backup Completo dos Dados Gerado!**\n\n"
            f"O arquivo JSON com a base consolidada de todos os registros do ateliê está pronto para download.\n\n"
            f"<a href=\"/exportar\" target=\"_blank\" class=\"btn-secondary\" style=\"display:inline-block; padding:10px 18px; font-size:15px !important; text-decoration:none;\">📥 Baixar Backup JSON</a>"
        )
        voice = "Arquivo de backup completo gerado para download."
        return {
            "success": True,
            "reply": msg,
            "voice_text": voice,
            "action": {"type": "download", "url": "/exportar", "filename": "export_all.json"},
            "suggestions": ["📄 Gerar PDF", "Ver estoque"]
        }

    # ── 2. AÇÕES DE PEDIDOS ──────────────────────────────────────────────────

    def _executar_mudar_status_pedido(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        pedidos = self.app.carregar_pedidos()
        if not pedidos:
            return {"reply": "Não há pedidos registrados para atualizar status.", "voice_text": "Não há pedidos registrados."}

        # Identificar novo status
        novo_status = None
        if "cancelar" in p_clean or "cancelado" in p_clean:
            novo_status = "Cancelado"
        elif "concluir" in p_clean or "concluido" in p_clean or "pronto" in p_clean:
            novo_status = "Concluído"
        elif "entregar" in p_clean or "entregue" in p_clean:
            novo_status = "Entregue"
        elif "producao" in p_clean or "em producao" in p_clean:
            novo_status = "Em produção"
        elif "pendente" in p_clean:
            novo_status = "Pendente"

        if not novo_status:
            return {
                "reply": "Para qual status você deseja alterar o pedido? Opções: *Pendente*, *Em produção*, *Concluído*, *Entregue* ou *Cancelado*.",
                "voice_text": "Informe o novo status desejado para o pedido.",
                "suggestions": ["Concluir pedido", "Mover para produção", "Cancelar pedido"]
            }

        # Identificar pedido por nome do cliente ou ID
        pedido_alvo = None
        for p in pedidos:
            c_clean = remover_acentos(p.get("cliente", ""))
            if c_clean and (c_clean in p_clean or any(palavra in p_clean for palavra in c_clean.split() if len(palavra) >= 3)):
                pedido_alvo = p
                break

        if not pedido_alvo:
            # Pega o pedido mais recente se for uma ação direta como "concluir último pedido"
            if "ultimo" in p_clean or len(pedidos) == 1:
                pedido_alvo = pedidos[0]
            else:
                linhas = [f"• **{p['cliente']}**: {p['quantidade']}x {p['produto_nome']} (`{p['status']}`)" for p in pedidos[:4]]
                return {
                    "reply": f"De qual cliente você deseja alterar o pedido para **{novo_status}**?\n\n" + "\n".join(linhas),
                    "voice_text": "De qual cliente você deseja atualizar o pedido?",
                    "suggestions": [f"Mudar status de {p['cliente']}" for p in pedidos[:3]]
                }

        # Executa a atualização chamando a lógica completa de status
        pedido_id = pedido_alvo["id"]
        now = self.app.agora()
        now_iso = now.isoformat()
        now_str = now.strftime("%d/%m/%Y %H:%M")
        user_id = user.get("id") or user.get("username")

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                if novo_status == "Cancelado" and bool(pedido_alvo.get("materiais_baixados")):
                    cur.execute("SELECT estoque_pronto FROM produtos WHERE id=?", (pedido_alvo["produto_id"],))
                    row_prod = cur.fetchone()
                    est_atual = int(row_prod[0] or 0) if row_prod else 0
                    qtd_ped = int(pedido_alvo["quantidade"] or 1)
                    cur.execute("UPDATE produtos SET estoque_pronto=?, updated_at=? WHERE id=?", (est_atual + qtd_ped, now_iso, pedido_alvo["produto_id"]))
                    cur.execute(
                        "INSERT INTO movimentacoes (id, tipo, material_nome, quantidade, unidade, motivo, data, usuario, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), "estoque_pronto", pedido_alvo["produto_nome"], qtd_ped, "unidades", f"Bolsa devolvida ao estoque de pronta-entrega (Cancelamento Ania)", now_str, user_id, now_iso)
                    )
                cur.execute("UPDATE pedidos SET status=?, updated_at=? WHERE id=?", (novo_status, now_iso, pedido_id))
                conn.commit()
            finally:
                conn.close()
        else:
            pedido_alvo["status"] = novo_status
            self.app.salvar_pedidos(pedidos)

        msg = (
            f"✅ **Status do Pedido Atualizado com Sucesso!** 🧾\n\n"
            f"• **Cliente**: **{pedido_alvo['cliente']}**\n"
            f"• **Produto**: {pedido_alvo.get('produto_emoji','👜')} {pedido_alvo['produto_nome']}\n"
            f"• **Novo Status**: `{novo_status}`\n"
            f"• **Atualizado por**: {user.get('nome') or user.get('username')}"
        )
        voice = f"Status do pedido de {pedido_alvo['cliente']} alterado para {novo_status} com sucesso."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos", "Consultar financeiro"]}

    def _executar_excluir_pedido(self, p_clean: str, prompt_orig: str) -> dict:
        pedidos = self.app.carregar_pedidos()
        if not pedidos:
            return {"reply": "Não há pedidos para excluir.", "voice_text": "Não há pedidos para excluir."}

        pedido_alvo = None
        for p in pedidos:
            c_clean = remover_acentos(p.get("cliente", ""))
            if c_clean and c_clean in p_clean:
                pedido_alvo = p
                break

        if not pedido_alvo:
            return {
                "reply": "Por favor informe o nome do cliente do pedido que deseja excluir. Exemplo: *\"Excluir pedido de Maria Silva\"*.",
                "voice_text": "Informe o nome do cliente do pedido que deseja excluir.",
                "suggestions": [f"Excluir pedido de {p['cliente']}" for p in pedidos[:3]]
            }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM pedidos WHERE id=?", (pedido_alvo["id"],))
            conn.commit()
            conn.close()
        else:
            pedidos = [p for p in pedidos if p["id"] != pedido_alvo["id"]]
            self.app.salvar_pedidos(pedidos)

        msg = f"🗑️ **Pedido de {pedido_alvo['cliente']}** ({pedido_alvo['produto_nome']}) foi **removido** com sucesso do sistema."
        voice = f"Pedido de {pedido_alvo['cliente']} removido com sucesso."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos", "Criar novo pedido"]}

    def _executar_criar_pedido(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        produtos = self.app.carregar_produtos()
        if not produtos:
            return {"reply": "Não há bolsas ou produtos cadastrados para registrar pedidos.", "voice_text": "Não há produtos cadastrados."}

        # Extrair quantidade
        match_qtd = re.search(r"(\d+)\s*(?:unidades?|pecas?|bolsas?|x)?", p_clean)
        qtd = int(match_qtd.group(1)) if match_qtd else 1

        # Encontrar produto/bolsa
        produto_alvo = None
        for p in produtos:
            p_nome_clean = remover_acentos(p["nome"])
            if p_nome_clean in p_clean or any(palavra in p_clean for palavra in p_nome_clean.split() if len(palavra) >= 4):
                produto_alvo = p
                break

        # Extrair nome do cliente
        cliente = "Cliente Balcão"
        match_cliente = re.search(r"(?:para|cliente|do cliente)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+?)(?:\s+de\b|\s+da\b|\s+do\b|\s+com\b|\.|$)", prompt_orig, re.IGNORECASE)
        if match_cliente:
            c_cand = match_cliente.group(1).strip()
            if len(c_cand) > 2 and c_cand.lower() not in ["uma", "um", "bolsa", "pedido"]:
                cliente = c_cand.title()

        if not produto_alvo:
            return {
                "reply": f"👜 Deseja abrir o formulário para registrar um pedido para **{cliente}**?",
                "voice_text": "Abrindo tela de novo pedido.",
                "action": {"type": "navigate", "url": "/pedidos/novo"},
                "suggestions": ["➕ Abrir Novo Pedido", "Ver produtos", "Ver pedidos"]
            }

        estoque_pronto = int(produto_alvo.get("estoque_pronto") or 0)
        usar_pronta = estoque_pronto >= qtd
        preco_unit = float(produto_alvo.get("preco_venda") or 0)
        valor_total = round(preco_unit * qtd, 2)
        dt_pedido = self.app.agora()

        novo_pedido = {
            "id": str(uuid.uuid4()),
            "cliente": cliente,
            "produto_id": produto_alvo["id"],
            "produto_nome": produto_alvo["nome"],
            "produto_emoji": produto_alvo.get("emoji", "👜"),
            "quantidade": qtd,
            "preco_unitario": preco_unit,
            "valor_total": valor_total,
            "status": "Concluído" if usar_pronta else "Pendente",
            "materiais_baixados": 1 if usar_pronta else 0,
            "usou_estoque_pronto": 1 if usar_pronta else 0,
            "data_pedido": dt_pedido.strftime("%d/%m/%Y"),
            "data_pedido_iso": dt_pedido.strftime("%Y-%m-%d %H:%M:%S"),
            "observacoes": "Registrado via Assistente Virtual Ania",
        }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            if usar_pronta:
                cur.execute("UPDATE produtos SET estoque_pronto=?, updated_at=? WHERE id=?", (estoque_pronto - qtd, dt_pedido.isoformat(), produto_alvo["id"]))
                cur.execute(
                    "INSERT INTO movimentacoes (id, tipo, material_nome, quantidade, unidade, motivo, data, usuario, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), "estoque_pronto", produto_alvo["nome"], qtd, "unidades", f"Atendimento de pedido de {cliente} (Ania)", dt_pedido.strftime("%d/%m/%Y %H:%M"), user.get("id"), dt_pedido.isoformat())
                )
            cur.execute(
                "INSERT INTO pedidos (id,cliente,produto_id,produto_nome,produto_emoji,quantidade,preco_unitario,valor_total,status,materiais_baixados,usou_estoque_pronto,data_pedido,data_pedido_iso,observacoes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (novo_pedido["id"], novo_pedido["cliente"], novo_pedido["produto_id"], novo_pedido["produto_nome"], novo_pedido["produto_emoji"], novo_pedido["quantidade"], novo_pedido["preco_unitario"], novo_pedido["valor_total"], novo_pedido["status"], novo_pedido["materiais_baixados"], novo_pedido["usou_estoque_pronto"], novo_pedido["data_pedido"], novo_pedido["data_pedido_iso"], novo_pedido["observacoes"], dt_pedido.isoformat(), dt_pedido.isoformat())
            )
            conn.commit()
            conn.close()
        else:
            if usar_pronta:
                produto_alvo["estoque_pronto"] = estoque_pronto - qtd
                self.app.salvar_produtos(produtos)
            lista_pedidos = self.app.carregar_json("pedidos.json")
            lista_pedidos.append(novo_pedido)
            self.app.salvar_json("pedidos.json", lista_pedidos)

        info_status = "✨ **Atendido Imediatamente (Pronta-Entrega)**" if usar_pronta else "⏳ **Pedido Pendente (Fabricação sob encomenda)**"
        msg = (
            f"✅ **Pedido Registrado com Sucesso!** 🧾\n\n"
            f"• **Cliente**: **{cliente}**\n"
            f"• **Produto**: {produto_alvo.get('emoji','👜')} **{qtd}x {produto_alvo['nome']}**\n"
            f"• **Valor Total**: **{formatar_moeda(valor_total)}**\n"
            f"• **Status**: {info_status}\n\n"
            f"O pedido já foi inserido e computado no sistema."
        )
        voice = f"Pedido de {qtd} {produto_alvo['nome']} para {cliente} registrado com sucesso no valor de {formatar_moeda(valor_total)}."
        return {
            "success": True,
            "reply": msg,
            "voice_text": voice,
            "suggestions": ["Ver pedidos pendentes", "Consultar estoque", "Resumo financeiro"]
        }

    # ── 3. AÇÕES DE ESTOQUE (CADASTRAR, ENTRADA, BAIXA, EXCLUIR) ─────────────

    def _executar_cadastrar_material(self, p_clean: str, prompt_orig: str) -> dict:
        # Extrair dados básicos do comando (ex: "cadastrar material Linha de Costura Branca categoria Aviamento 10 unidades custo 5 reais minimo 2")
        nome_match = re.search(r"(?:material|insumo)\s+([A-Za-zÀ-ÖØ-öø-ÿ0-9\s]+?)(?:\s+categoria|\s+com\b|\s+qtd|\s+quantidade|\.|$)", prompt_orig, re.IGNORECASE)
        nome = nome_match.group(1).strip().title() if nome_match else ""

        if not nome or len(nome) < 2:
            return {
                "reply": "📝 Deseja abrir o formulário para cadastrar um novo material com foto e GTIN?",
                "voice_text": "Abrindo formulário de cadastro de material.",
                "action": {"type": "navigate", "url": "/adicionar"},
                "suggestions": ["➕ Abrir formulário de material", "Ver estoque"]
            }

        # Categoria
        categoria = "Outros"
        for cat in self.app.CATEGORIAS:
            if remover_acentos(cat) in p_clean:
                categoria = cat
                break

        # Unidade
        unidade = "unidades"
        for u in self.app.UNIDADES:
            if remover_acentos(u) in p_clean:
                unidade = u
                break

        # Quantidade
        qtd_match = re.search(r"(?:quantidade|qtd|com)\s+(\d+(?:[.,]\d+)?)", p_clean)
        qtd = float(qtd_match.group(1).replace(",", ".")) if qtd_match else 1.0

        # Custo
        custo_match = re.search(r"(?:custo|valor|preco|custando|de)\s+(?:r\$\s*)?(\d+(?:[.,]\d+)?)", p_clean)
        custo = float(custo_match.group(1).replace(",", ".")) if custo_match else 0.0

        # Qtd Mínima
        min_match = re.search(r"(?:minimo|minima)\s+(\d+(?:[.,]\d+)?)", p_clean)
        qtd_min = float(min_match.group(1).replace(",", ".")) if min_match else 1.0

        # GTIN se mencionado
        gtin_match = re.search(r"\b(\d{8,14})\b", prompt_orig)
        gtin = gtin_match.group(1) if gtin_match else ""

        emoji = self.app.CATEGORIAS_EMOJI.get(categoria, "📦")
        now = self.app.agora().isoformat()
        mat_id = str(uuid.uuid4())

        materiais = self.app.carregar_materiais()
        if any(m["nome"].strip().lower() == nome.lower() for m in materiais):
            return {
                "reply": f"⚠️ Já existe um material chamado **{nome}** no estoque. Se deseja adicionar mais unidades, diga *\"Dar entrada de {qtd} em {nome}\"*.",
                "voice_text": f"O material {nome} já existe no estoque.",
                "suggestions": [f"Dar entrada em {nome}", "Consultar estoque"]
            }

        novo_mat = {
            "id": mat_id,
            "nome": nome,
            "categoria": categoria,
            "emoji": emoji,
            "quantidade": qtd,
            "unidade": unidade,
            "quantidade_minima": qtd_min,
            "custo": custo,
            "gtin": gtin,
            "foto": "",
        }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO materiais (id,nome,categoria,emoji,quantidade,unidade,quantidade_minima,custo,gtin,foto,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (mat_id, nome, categoria, emoji, qtd, unidade, qtd_min, custo, gtin, "", now, now)
            )
            conn.commit()
            conn.close()
        else:
            materiais.append(novo_mat)
            self.app.salvar_materiais(materiais)

        msg = (
            f"✅ **Novo Material Cadastrado com Sucesso!** 📦\n\n"
            f"• **Material**: {emoji} **{nome}**\n"
            f"• **Categoria**: {categoria}\n"
            f"• **Estoque Inicial**: **{qtd} {unidade}**\n"
            f"• **Custo Unitário**: {formatar_moeda(custo)}\n"
            f"• **Estoque Mínimo**: {qtd_min} {unidade}\n"
            + (f"• **GTIN**: `{gtin}`\n" if gtin else "")
        )
        voice = f"Material {nome} cadastrado com sucesso com estoque inicial de {qtd} {unidade}."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver estoque", "Dar baixa", "Alertas"]}

    def _executar_dar_entrada_material(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        materiais = self.app.carregar_materiais()
        if not materiais:
            return {"reply": "Não há materiais no estoque.", "voice_text": "Estoque vazio."}

        match_qtd = re.search(r"(\d+(?:[.,]\d+)?)", p_clean)
        qtd = float(match_qtd.group(1).replace(",", ".")) if match_qtd else 1.0

        material_alvo = None
        for m in materiais:
            n_clean = remover_acentos(m["nome"])
            if n_clean in p_clean or any(palavra in p_clean for palavra in n_clean.split() if len(palavra) >= 4):
                material_alvo = m
                break

        if not material_alvo:
            return {
                "reply": "Por favor informe o nome do material e a quantidade que deseja adicionar. Exemplo: *\"Dar entrada de 5 metros de Courino\"*.",
                "voice_text": "Informe o nome do material e a quantidade para dar entrada.",
                "suggestions": [f"Dar entrada em {m['nome']}" for m in materiais[:3]]
            }

        estoque_atual = float(material_alvo.get("quantidade") or 0)
        novo_estoque = round(estoque_atual + qtd, 3)
        dt_agora = self.app.agora()
        dt_iso = dt_agora.isoformat()
        dt_str = dt_agora.strftime("%d/%m/%Y %H:%M")
        user_id = user.get("id") or user.get("username")

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE materiais SET quantidade=?, updated_at=? WHERE id=?", (novo_estoque, dt_iso, material_alvo["id"]))
            cur.execute(
                "INSERT INTO movimentacoes (id, tipo, material_nome, quantidade, unidade, motivo, data, usuario, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "entrada", material_alvo["nome"], qtd, material_alvo["unidade"], "Entrada manual via Ania", dt_str, user_id, dt_iso)
            )
            conn.commit()
            conn.close()
        else:
            material_alvo["quantidade"] = novo_estoque
            self.app.salvar_materiais(materiais)

        msg = (
            f"✅ **Entrada no Estoque Registrada!** 📦\n\n"
            f"• **Material**: {material_alvo.get('emoji','📦')} **{material_alvo['nome']}**\n"
            f"• **Adicionado**: +{qtd} {material_alvo['unidade']}\n"
            f"• **Novo Saldo**: **{novo_estoque} {material_alvo['unidade']}**\n"
            f"• **Registrado por**: {user.get('nome') or user.get('username')}"
        )
        voice = f"Entrada de {qtd} {material_alvo['unidade']} de {material_alvo['nome']} realizada. Novo saldo: {novo_estoque}."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Consultar estoque", "Ver alertas"]}

    def _executar_dar_baixa(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        materiais = self.app.carregar_materiais()
        if not materiais:
            return {"reply": "Não há materiais no estoque para dar baixa.", "voice_text": "Estoque vazio."}

        match_qtd = re.search(r"(\d+(?:[.,]\d+)?)", p_clean)
        qtd = float(match_qtd.group(1).replace(",", ".")) if match_qtd else 1.0

        material_alvo = None
        for m in materiais:
            n_clean = remover_acentos(m["nome"])
            if n_clean in p_clean or any(palavra in p_clean for palavra in n_clean.split() if len(palavra) >= 4):
                material_alvo = m
                break

        if not material_alvo:
            return {
                "reply": "✂️ Para dar baixa, por favor informe o **nome do material** e a **quantidade**. Exemplo: *\"Dar baixa de 2 zíperes por costura\"*.",
                "voice_text": "Por favor informe o nome do material e a quantidade que deseja dar baixa.",
                "action": {"type": "navigate", "url": "/baixa"},
                "suggestions": ["Dar baixa de couro", "Dar baixa de zíper", "Abrir tela de baixa"]
            }

        motivo = "Uso em produção (via Ania)"
        for m_teste in ["costura", "corte", "defeito", "descarte", "prototipo", "perda", "teste", "amostra"]:
            if m_teste in p_clean:
                motivo = m_teste.capitalize()
                break

        estoque_atual = float(material_alvo.get("quantidade") or 0)
        if estoque_atual < qtd:
            return {
                "reply": f"⚠️ **Estoque Insuficiente**: O material **{material_alvo['nome']}** possui apenas **{estoque_atual} {material_alvo['unidade']}** em estoque (você solicitou baixa de {qtd}).",
                "voice_text": f"Estoque insuficiente. Temos apenas {estoque_atual} {material_alvo['unidade']} de {material_alvo['nome']}.",
                "suggestions": ["Consultar estoque", "Ver alertas"]
            }

        novo_estoque = round(estoque_atual - qtd, 3)
        dt_agora = self.app.agora()
        dt_iso = dt_agora.isoformat()
        dt_str = dt_agora.strftime("%d/%m/%Y %H:%M")
        user_id = user.get("id") or user.get("username")

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE materiais SET quantidade=?, updated_at=? WHERE id=?", (novo_estoque, dt_iso, material_alvo["id"]))
            cur.execute(
                "INSERT INTO movimentacoes (id, tipo, material_nome, quantidade, unidade, motivo, data, usuario, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "saida", material_alvo["nome"], qtd, material_alvo["unidade"], f"{motivo} (Assistente Ania)", dt_str, user_id, dt_iso)
            )
            conn.commit()
            conn.close()
        else:
            material_alvo["quantidade"] = novo_estoque
            self.app.salvar_materiais(materiais)

        msg = (
            f"✅ **Baixa Realizada com Sucesso!** ✂️\n\n"
            f"• **Material**: {material_alvo.get('emoji','📦')} **{material_alvo['nome']}**\n"
            f"• **Quantidade Baixada**: -{qtd} {material_alvo['unidade']}\n"
            f"• **Novo Saldo em Estoque**: **{novo_estoque} {material_alvo['unidade']}**\n"
            f"• **Motivo Registrado**: *{motivo}*\n"
            f"• **Operador**: {user.get('nome') or user.get('username')}"
        )
        voice = f"Baixa de {qtd} {material_alvo['unidade']} de {material_alvo['nome']} registrada com sucesso. Novo saldo: {novo_estoque}."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Consultar estoque", "Ver alertas", "Ver pedidos"]}

    def _executar_excluir_material(self, p_clean: str, prompt_orig: str) -> dict:
        materiais = self.app.carregar_materiais()
        material_alvo = None
        for m in materiais:
            n_clean = remover_acentos(m["nome"])
            if n_clean in p_clean:
                material_alvo = m
                break

        if not material_alvo:
            return {
                "reply": "Qual material você deseja excluir? Exemplo: *\"Excluir material Retalho de Couro\"*.",
                "voice_text": "Informe qual material deseja excluir.",
                "suggestions": [f"Excluir {m['nome']}" for m in materiais[:3]]
            }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM materiais WHERE id=?", (material_alvo["id"],))
            conn.commit()
            conn.close()
        else:
            materiais = [m for m in materiais if m["id"] != material_alvo["id"]]
            self.app.salvar_materiais(materiais)

        msg = f"🗑️ Material **{material_alvo['nome']}** excluído com sucesso do estoque."
        voice = f"Material {material_alvo['nome']} excluído com sucesso."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Consultar estoque", "Cadastrar material"]}

    # ── 4. AÇÕES DE PRODUTOS & BOLSAS ────────────────────────────────────────

    def _executar_cadastrar_produto(self, p_clean: str, prompt_orig: str) -> dict:
        nome_match = re.search(r"(?:bolsa|produto)\s+([A-Za-zÀ-ÖØ-öø-ÿ0-9\s]+?)(?:\s+com\s+preco|\s+preco|\s+valor|\.|$)", prompt_orig, re.IGNORECASE)
        nome = nome_match.group(1).strip().title() if nome_match else ""

        if not nome or len(nome) < 2:
            return {
                "reply": "👜 Deseja abrir a página para cadastrar uma nova bolsa com receita e custos?",
                "voice_text": "Abrindo cadastro de novo produto.",
                "action": {"type": "navigate", "url": "/produtos/novo"},
                "suggestions": ["➕ Abrir Novo Produto", "Ver catálogo"]
            }

        preco_match = re.search(r"(?:preco|valor|de)\s+(?:r\$\s*)?(\d+(?:[.,]\d+)?)", p_clean)
        preco = float(preco_match.group(1).replace(",", ".")) if preco_match else 0.0

        estoque_match = re.search(r"(\d+)\s*(?:pecas?\s+prontas?|prontas?)", p_clean)
        est_pronto = int(estoque_match.group(1)) if estoque_match else 0

        emoji = "👜"
        for e in ["👜", "🎒", "👝", "💼", "🧳", "👛"]:
            if e in prompt_orig:
                emoji = e
                break

        novo_prod = {
            "id": str(uuid.uuid4()),
            "nome": nome,
            "emoji": emoji,
            "preco_venda": preco,
            "receita": [],
            "gtin": "",
            "estoque_pronto": est_pronto,
        }

        produtos = self.app.carregar_produtos()
        produtos.append(novo_prod)
        self.app.salvar_produtos(produtos)

        msg = (
            f"✅ **Bolsa Cadastrada com Sucesso!** 👜\n\n"
            f"• **Modelo**: {emoji} **{nome}**\n"
            f"• **Preço de Venda**: **{formatar_moeda(preco)}**\n"
            f"• **Estoque Inicial de Peças Prontas**: {est_pronto} unidade(s)\n\n"
            f"Você já pode registrar pedidos deste produto ou adicionar sua receita técnica."
        )
        voice = f"Produto {nome} cadastrado com sucesso com preço de {formatar_moeda(preco)}."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Criar pedido desta bolsa", "Ver produtos"]}

    def _executar_ajuste_estoque_pronto(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        produtos = self.app.carregar_produtos()
        if not produtos:
            return {"reply": "Não há produtos cadastrados.", "voice_text": "Não há produtos."}

        match_qtd = re.search(r"(\d+)", p_clean)
        qtd = int(match_qtd.group(1)) if match_qtd else 1

        is_remover = any(w in p_clean for w in ["remover", "retirar", "diminuir", "subtrair"])
        acao = "remover" if is_remover else "adicionar"

        produto_alvo = None
        for p in produtos:
            p_clean_n = remover_acentos(p["nome"])
            if p_clean_n in p_clean or any(palavra in p_clean for palavra in p_clean_n.split() if len(palavra) >= 4):
                produto_alvo = p
                break

        if not produto_alvo:
            return {
                "reply": "De qual bolsa você deseja ajustar o estoque de peças prontas? Exemplo: *\"Adicionar 2 peças prontas na Bolsa Tote\"*.",
                "voice_text": "Informe a bolsa e a quantidade para ajustar o estoque de peças prontas.",
                "suggestions": [f"Ajustar {p['nome']}" for p in produtos[:3]]
            }

        est_atual = int(produto_alvo.get("estoque_pronto") or 0)
        novo_est = max(0, est_atual - qtd) if is_remover else (est_atual + qtd)
        dt_agora = self.app.agora()
        dt_iso = dt_agora.isoformat()
        dt_str = dt_agora.strftime("%d/%m/%Y %H:%M")
        user_id = user.get("id") or user.get("username")
        motivo = f"Ajuste de estoque pronto via Ania ({acao} {qtd})"

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE produtos SET estoque_pronto=?, updated_at=? WHERE id=?", (novo_est, dt_iso, produto_alvo["id"]))
            cur.execute(
                "INSERT INTO movimentacoes (id, tipo, material_nome, quantidade, unidade, motivo, data, usuario, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "estoque_pronto", produto_alvo["nome"], qtd if not is_remover else -qtd, "unidades", motivo, dt_str, user_id, dt_iso)
            )
            conn.commit()
            conn.close()
        else:
            produto_alvo["estoque_pronto"] = novo_est
            self.app.salvar_produtos(produtos)

        msg = (
            f"✅ **Estoque de Peças Prontas Atualizado!** 🛍️\n\n"
            f"• **Produto**: {produto_alvo.get('emoji','👜')} **{produto_alvo['nome']}**\n"
            f"• **Operação**: {'Adicionadas +' if not is_remover else 'Removidas -'}{qtd} peça(s)\n"
            f"• **Novo Estoque de Pronta-Entrega**: **{novo_est} pronta(s)**"
        )
        voice = f"Estoque pronto de {produto_alvo['nome']} atualizado para {novo_est} peças."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver produtos", "Criar pedido"]}

    def _executar_excluir_produto(self, p_clean: str, prompt_orig: str) -> dict:
        produtos = self.app.carregar_produtos()
        produto_alvo = None
        for p in produtos:
            p_clean_n = remover_acentos(p["nome"])
            if p_clean_n in p_clean:
                produto_alvo = p
                break

        if not produto_alvo:
            return {
                "reply": "Qual bolsa você deseja excluir? Exemplo: *\"Excluir produto Bolsa Tote\"*.",
                "voice_text": "Informe a bolsa que deseja excluir.",
                "suggestions": [f"Excluir {p['nome']}" for p in produtos[:3]]
            }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM produtos WHERE id=?", (produto_alvo["id"],))
            conn.commit()
            conn.close()
        else:
            produtos = [p for p in produtos if p["id"] != produto_alvo["id"]]
            self.app.salvar_produtos(produtos)

        msg = f"🗑️ Produto **{produto_alvo['nome']}** removido do catálogo com sucesso."
        voice = f"Produto {produto_alvo['nome']} removido com sucesso."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver produtos", "Criar produto"]}

    # ── 5. AÇÕES DE SOBRAS & RETALHOS ────────────────────────────────────────

    def _executar_cadastrar_sobra(self, p_clean: str, prompt_orig: str) -> dict:
        desc_match = re.search(r"(?:sobra|retalho)\s+(?:de\s+)?([A-Za-zÀ-ÖØ-öø-ÿ0-9\s]+?)(?:\s+com\s+qtd|\s+qtd|\.|$)", prompt_orig, re.IGNORECASE)
        desc = desc_match.group(1).strip().title() if desc_match else "Retalho de Material"

        qtd_match = re.search(r"(\d+(?:[.,]\d+)?)", p_clean)
        qtd = float(qtd_match.group(1).replace(",", ".")) if qtd_match else 1.0

        unidade = "metros"
        for u in self.app.UNIDADES:
            if remover_acentos(u) in p_clean:
                unidade = u
                break

        nova_sobra = {
            "id": str(uuid.uuid4()),
            "material_id": "",
            "descricao": desc,
            "quantidade": qtd,
            "unidade": unidade,
            "data": self.app.agora().strftime("%d/%m/%Y"),
            "status": "Disponível",
        }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sobras (id,material_id,descricao,quantidade,unidade,data,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (nova_sobra["id"], "", desc, qtd, unidade, nova_sobra["data"], "Disponível", self.app.agora().isoformat(), self.app.agora().isoformat())
            )
            conn.commit()
            conn.close()
        else:
            sobras = self.app.carregar_sobras()
            sobras.append(nova_sobra)
            self.app.salvar_json("sobras.json", sobras)

        msg = (
            f"✅ **Sobra/Retalho Registrado para Reaproveitamento!** ♻️\n\n"
            f"• **Descrição**: **{desc}**\n"
            f"• **Quantidade**: {qtd} {unidade}\n"
            f"• **Status**: `Disponível`"
        )
        voice = f"Sobra de {desc} registrada com sucesso."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver sobras", "Consultar estoque"]}

    def _executar_acao_sobra(self, p_clean: str, prompt_orig: str) -> dict:
        sobras = self.app.carregar_sobras()
        if not sobras:
            return {"reply": "Não há sobras registradas.", "voice_text": "Não há sobras registradas."}

        novo_status = "Descartado" if "descartar" in p_clean else "Reaproveitado"
        sobra_alvo = next((s for s in sobras if remover_acentos(s.get("descricao", "")) in p_clean), sobras[0] if len(sobras) == 1 else None)

        if not sobra_alvo:
            return {
                "reply": f"Qual sobra você deseja marcar como **{novo_status}**?\n\n" + "\n".join([f"• {s['descricao']} ({s['quantidade']} {s['unidade']})" for s in sobras[:3]]),
                "voice_text": "Qual sobra você deseja atualizar?",
                "suggestions": [f"{novo_status} {s['descricao']}" for s in sobras[:3]]
            }

        now_iso = self.app.agora().isoformat()
        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE sobras SET status=?, updated_at=? WHERE id=?", (novo_status, now_iso, sobra_alvo["id"]))
            conn.commit()
            conn.close()
        else:
            sobra_alvo["status"] = novo_status
            self.app.salvar_json("sobras.json", sobras)

        msg = f"♻️ A sobra **{sobra_alvo['descricao']}** foi marcada como **{novo_status}**."
        voice = f"Sobra marcada como {novo_status}."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver sobras", "Consultar estoque"]}

    def _executar_excluir_sobra(self, p_clean: str, prompt_orig: str) -> dict:
        sobras = self.app.carregar_sobras()
        sobra_alvo = next((s for s in sobras if remover_acentos(s.get("descricao", "")) in p_clean), None)
        if not sobra_alvo:
            return {"reply": "Qual sobra você deseja excluir?", "voice_text": "Qual sobra deseja excluir?"}

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM sobras WHERE id=?", (sobra_alvo["id"],))
            conn.commit()
            conn.close()
        else:
            sobras = [s for s in sobras if s["id"] != sobra_alvo["id"]]
            self.app.salvar_json("sobras.json", sobras)

        msg = f"🗑️ Sobra **{sobra_alvo['descricao']}** excluída."
        voice = f"Sobra excluída."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Ver sobras"]}

    # ── 6. AÇÕES FINANCEIRAS (DESPESAS) ──────────────────────────────────────

    def _executar_cadastrar_despesa(self, p_clean: str, prompt_orig: str) -> dict:
        valor_match = re.search(r"(?:de|valor|r\$)\s*(\d+(?:[.,]\d+)?)", p_clean)
        valor = float(valor_match.group(1).replace(",", ".")) if valor_match else 0.0

        if valor <= 0:
            return {
                "reply": "💰 Para cadastrar uma despesa, informe o valor e a descrição. Exemplo: *\"Cadastrar despesa de 50 reais com Linhas e Zíperes\"*.",
                "voice_text": "Informe o valor e a descrição da despesa.",
                "action": {"type": "navigate", "url": "/financeiro"},
                "suggestions": ["➕ Abrir Financeiro", "Resumo financeiro"]
            }

        desc_match = re.search(r"(?:com|para|de)\s+([A-Za-zÀ-ÖØ-öø-ÿ0-9\s]+?)(?:\s+categoria|\.|$)", prompt_orig, re.IGNORECASE)
        desc = desc_match.group(1).strip().title() if desc_match else "Despesa Operacional"

        categoria = "Insumos"
        for cat in ["Insumos", "Ferramentas", "Embalagem", "Manutenção", "Frete", "Outros"]:
            if remover_acentos(cat) in p_clean:
                categoria = cat
                break

        nova_desp = {
            "id": str(uuid.uuid4()),
            "descricao": desc,
            "valor": valor,
            "categoria": categoria,
            "data": self.app.agora().strftime("%d/%m/%Y"),
            "created_at": self.app.agora().isoformat()
        }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO despesas (id,descricao,valor,categoria,data,created_at) VALUES (?,?,?,?,?,?)",
                (nova_desp["id"], desc, valor, categoria, nova_desp["data"], nova_desp["created_at"])
            )
            conn.commit()
            conn.close()
        else:
            despesas = self.app.carregar_despesas()
            despesas.append(nova_desp)
            self.app.salvar_json("despesas.json", despesas)

        msg = (
            f"✅ **Despesa Registrada no Financeiro!** 💰\n\n"
            f"• **Descrição**: **{desc}**\n"
            f"• **Valor**: **{formatar_moeda(valor)}**\n"
            f"• **Categoria**: {categoria}\n"
            f"• **Data**: {nova_desp['data']}"
        )
        voice = f"Despesa de {formatar_moeda(valor)} com {desc} registrada com sucesso."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Resumo financeiro", "📄 Gerar PDF"]}

    def _executar_excluir_despesa(self, p_clean: str, prompt_orig: str) -> dict:
        despesas = self.app.carregar_despesas()
        if not despesas:
            return {"reply": "Não há despesas registradas.", "voice_text": "Não há despesas."}

        desp_alvo = next((d for d in despesas if remover_acentos(d.get("descricao", "")) in p_clean), despesas[0] if len(despesas) == 1 else None)
        if not desp_alvo:
            return {
                "reply": "Qual despesa você deseja excluir?\n\n" + "\n".join([f"• {d['descricao']} ({formatar_moeda(d['valor'])})" for d in despesas[:3]]),
                "voice_text": "Qual despesa deseja excluir?",
                "suggestions": [f"Excluir despesa de {d['descricao']}" for d in despesas[:3]]
            }

        if self.app.USE_SQLITE:
            self.app.init_db()
            conn = sqlite3.connect(self.app.DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM despesas WHERE id=?", (desp_alvo["id"],))
            conn.commit()
            conn.close()
        else:
            despesas = [d for d in despesas if d["id"] != desp_alvo["id"]]
            self.app.salvar_json("despesas.json", despesas)

        msg = f"🗑️ Despesa **{desp_alvo['descricao']}** ({formatar_moeda(desp_alvo['valor'])}) foi excluída."
        voice = f"Despesa de {desp_alvo['descricao']} excluída."
        return {"success": True, "reply": msg, "voice_text": voice, "suggestions": ["Resumo financeiro"]}

    # ── 7. AÇÕES DE USUÁRIOS ─────────────────────────────────────────────────

    def _executar_cadastrar_usuario(self, p_clean: str, prompt_orig: str) -> dict:
        msg = (
            f"👥 **Gestão de Usuários**\n\n"
            f"Para cadastrar um novo usuário com senha segura e atribuição de múltiplos papéis, abra a tela de cadastro:\n\n"
            f"<a href=\"/usuarios/novo\" class=\"btn-primary\" style=\"display:inline-block; padding:10px 18px; font-size:15px !important; text-decoration:none;\">➕ Novo Usuário</a>"
        )
        voice = "Abrindo tela de cadastro de novos usuários."
        return {"reply": msg, "voice_text": voice, "action": {"type": "navigate", "url": "/usuarios/novo"}, "suggestions": ["Ver usuários", "Minhas permissões"]}

    # ── 8. MÉTODOS DE AJUDA, PERMISSÕES E CONSULTAS ──────────────────────────

    def _responder_ajuda(self, user_nome: str, roles: list) -> dict:
        msg = (
            f"✨ **Olá, {user_nome}! Eu sou a Ania**, sua assistente inteligente completa do Ateliê Haiti. 🧵\n\n"
            f"Comigo você pode executar **todas as ações do sistema** por **voz 🎙️ ou texto**:\n\n"
            f"📄 **Relatórios e Documentos:**\n"
            f"• *\"Gerar relatório em PDF\"* | *\"Exportar planilha Excel\"*\n\n"
            f"🧾 **Gestão de Pedidos:**\n"
            f"• *\"Criar pedido para Maria Silva de 2 Bolsas Tote\"*\n"
            f"• *\"Concluir pedido de Carlos\"* | *\"Cancelar pedido de Ana\"*\n\n"
            f"📦 **Estoque e Insumos:**\n"
            f"• *\"Quanto couro temos em estoque?\"* | *\"Buscar GTIN 789...\"*\n"
            f"• *\"Dar baixa de 2 zíperes por costura\"* | *\"Dar entrada de 10 metros de courino\"*\n"
            f"• *\"Cadastrar material Tecido Jeans, categoria Tecido...\"*\n\n"
            f"👜 **Produtos & Peças Prontas:**\n"
            f"• *\"Cadastrar bolsa Carteira Clutch com preço 80 reais\"*\n"
            f"• *\"Adicionar 3 peças prontas na Bolsa Tote\"*\n\n"
            f"💰 **Financeiro & Despesas:**\n"
            f"• *\"Qual o faturamento e saldo?\"* | *\"Cadastrar despesa de 40 reais com linhas\"*\n\n"
            f"🔒 **Acessos & Segurança:**\n"
            f"• *\"Quais são as minhas permissões?\"*"
        )
        voice = f"Olá {user_nome}! Eu sou a Ania. Você pode me pedir para gerar relatórios em PDF, criar pedidos, dar baixa de materiais, cadastrar produtos e consultar o financeiro por voz ou texto."
        return {
            "reply": msg,
            "voice_text": voice,
            "suggestions": ["📄 Enviar relatório em PDF", "📦 Consultar estoque", "🧾 Criar novo pedido", "💰 Resumo financeiro", "📊 Ver alertas"]
        }

    def _responder_minhas_permissoes(self, user: dict, user_nome: str, roles: list) -> dict:
        roles_str = ", ".join(roles) if roles else "Nenhum papel atribuído"
        is_admin = "Admin" in roles

        tabs_permitidas = []
        for tab in self.app.SYSTEM_TABS:
            t_id = tab["id"]
            if is_admin or self.app.user_has_permission(t_id, "read") or (t_id in ("adicionar", "baixa") and self.app.user_has_permission(t_id, "create")):
                tabs_permitidas.append(f"{tab['emoji']} **{tab['name']}**")

        msg = (
            f"👤 **Perfil e Acessos de {user_nome}**\n\n"
            f"• **Papéis Ativos**: `{roles_str}`\n"
            f"• **Nível**: {'👑 Administrador (Acesso Total a Todas as Ações)' if is_admin else '🧵 Usuário com Permissões Granulares'}\n\n"
            f"📋 **Módulos que você pode operar:**\n" +
            ("\n".join([f"• {t}" for t in tabs_permitidas]) if tabs_permitidas else "• *Nenhum módulo liberado atualmente.*")
        )
        voice = f"{user_nome}, seu perfil possui os papéis: {roles_str}. Você tem acesso a {len(tabs_permitidas)} módulos do sistema."
        return {
            "reply": msg,
            "voice_text": voice,
            "suggestions": ["📄 Gerar PDF", "📦 Consultar estoque", "🧾 Pedidos", "📊 Alertas"]
        }

    def _verificar_navegacao(self, p_clean: str):
        rotas = [
            (["ir para estoque", "abrir estoque", "me leve para o estoque", "tela de estoque", "pagina de estoque"], "estoque", "/estoque", "Estoque"),
            (["ir para adicionar", "abrir adicionar", "tela de adicionar", "pagina de adicionar"], "adicionar", "/adicionar", "Adicionar Material"),
            (["ir para baixa", "abrir baixa", "tela de baixa", "pagina de baixa"], "baixa", "/baixa", "Dar Baixa"),
            (["ir para produtos", "abrir produtos", "catalogo de bolsas", "tela de produtos", "pagina de produtos"], "produtos", "/produtos", "Produtos & Receitas"),
            (["ir para pedidos", "abrir pedidos", "tela de pedidos", "pagina de pedidos"], "pedidos", "/pedidos", "Pedidos dos Clientes"),
            (["ir para sobras", "abrir sobras", "tela de sobras", "pagina de sobras"], "sobras", "/sobras", "Sobras & Reaproveitamento"),
            (["ir para financeiro", "abrir financeiro", "tela de financeiro", "pagina de financeiro"], "financeiro", "/financeiro", "Financeiro"),
            (["ir para alertas", "abrir alertas", "ir para relatorios", "abrir relatorios", "tela de relatorios"], "relatorios", "/alertas", "Alertas e Relatórios"),
            (["ir para usuarios", "abrir usuarios", "tela de usuarios", "pagina de usuarios"], "usuarios", "/usuarios", "Gestão de Usuários"),
            (["ir para papeis", "abrir papeis", "abrir permissoes", "tela de papeis"], "roles", "/roles", "Papéis & Permissões"),
            (["ir para minha conta", "abrir minha conta", "editar meu perfil"], "estoque", "/minha-conta", "Minha Conta"),
        ]
        for triggers, recurso, url, nome in rotas:
            if any(t in p_clean for t in triggers):
                return recurso, url, nome
        return None

    def _busca_material_direta(self, p_clean: str) -> bool:
        materiais = self.app.carregar_materiais()
        for m in materiais:
            nm = remover_acentos(m.get("nome", ""))
            if nm and len(nm) >= 3 and nm in p_clean:
                return True
        return False

    def _consultar_estoque(self, p_clean: str, prompt_orig: str) -> dict:
        materiais = self.app.carregar_materiais()
        if not materiais:
            return {
                "reply": "📦 Não há materiais cadastrados no estoque ainda.",
                "voice_text": "Não há materiais cadastrados no estoque ainda.",
                "suggestions": ["➕ Cadastrar material", "Ver produtos"]
            }

        # Busca por GTIN
        match_gtin = re.search(r"\b(\d{6,14})\b", prompt_orig)
        if match_gtin:
            gtin_num = match_gtin.group(1)
            mat_gtin = next((m for m in materiais if (m.get("gtin") or "").strip() == gtin_num), None)
            if mat_gtin:
                val_total = float(mat_gtin.get("quantidade") or 0) * float(mat_gtin.get("custo") or 0)
                msg = (
                    f"🔍 **Material Encontrado por GTIN {gtin_num}**:\n\n"
                    f"• **Item**: {mat_gtin.get('emoji', '📦')} **{mat_gtin['nome']}**\n"
                    f"• **Quantidade em Estoque**: **{mat_gtin['quantidade']} {mat_gtin['unidade']}**\n"
                    f"• **Custo Unitário**: {formatar_moeda(mat_gtin['custo'])}\n"
                    f"• **Valor Total em Estoque**: {formatar_moeda(val_total)}\n"
                    f"• **Estoque Mínimo**: {mat_gtin.get('quantidade_minima', 0)} {mat_gtin['unidade']}"
                )
                voice = f"Material encontrado: {mat_gtin['nome']}. Temos {mat_gtin['quantidade']} {mat_gtin['unidade']} em estoque."
                return {"reply": msg, "voice_text": voice, "suggestions": [f"Dar baixa de {mat_gtin['nome']}", "Ver estoque"]}

        # Busca específica por nome
        encontrados = []
        for m in materiais:
            nome_clean = remover_acentos(m.get("nome", ""))
            cat_clean = remover_acentos(m.get("categoria", ""))
            if nome_clean in p_clean or any(word in p_clean for word in nome_clean.split() if len(word) > 2) or (cat_clean and cat_clean in p_clean):
                encontrados.append(m)

        if encontrados and len(encontrados) <= 4:
            linhas = []
            voice_parts = []
            for m in encontrados:
                qtd = float(m.get("quantidade") or 0)
                qtd_min = float(m.get("quantidade_minima") or 0)
                status_alerta = " ⚠️ *(Abaixo do mínimo!)*" if qtd <= qtd_min else " ✅ *(Normal)*"
                linhas.append(
                    f"• {m.get('emoji','📦')} **{m['nome']}**: **{m['quantidade']} {m['unidade']}** (Custo: {formatar_moeda(m['custo'])}){status_alerta}"
                )
                voice_parts.append(f"{m['nome']}: {m['quantidade']} {m['unidade']}")

            msg = "📦 **Consulta de Estoque:**\n\n" + "\n".join(linhas)
            voice = "Temos em estoque: " + ", ".join(voice_parts) + "."
            return {"reply": msg, "voice_text": voice, "suggestions": ["Dar baixa", "Ver alertas", "📄 Gerar PDF"]}

        # Visão Geral
        total_itens = len(materiais)
        valor_total = sum(float(m.get("quantidade") or 0) * float(m.get("custo") or 0) for m in materiais)
        abaixo_min = [m for m in materiais if float(m.get("quantidade") or 0) <= float(m.get("quantidade_minima") or 0)]

        msg = (
            f"📦 **Visão Geral do Estoque do Ateliê**\n\n"
            f"• **Materiais Cadastrados**: {total_itens} insumos diferentes\n"
            f"• **Valor Total em Estoque**: **{formatar_moeda(valor_total)}**\n"
            f"• **Itens com Alerta (Abaixo do Mínimo)**: {len(abaixo_min)} item(ns)\n\n"
            f"Para consultar um material específico, diga: *\"Quanto couro temos?\"* ou *\"Qual o estoque de zíper?\"*."
        )
        voice = f"O estoque possui {total_itens} materiais cadastrados, somando {formatar_moeda(valor_total)}. Temos {len(abaixo_min)} itens abaixo do estoque mínimo."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Quais itens estão acabando?", "Consultar couro", "Dar baixa", "📄 Gerar PDF"]}

    def _consultar_alertas_e_resumo(self) -> dict:
        materiais = self.app.carregar_materiais()
        pedidos = self.app.carregar_pedidos()

        criticos = [m for m in materiais if float(m.get("quantidade") or 0) <= float(m.get("quantidade_minima") or 0)]
        zerados = [m for m in materiais if float(m.get("quantidade") or 0) <= 0]
        pedidos_pendentes = [p for p in pedidos if p.get("status") in ("Pendente", "Em produção")]

        linhas = []
        if zerados:
            linhas.append("🚨 **Materiais Esgotados (Qtd 0):**")
            for z in zerados[:4]:
                linhas.append(f"• {z.get('emoji','❌')} **{z['nome']}**: 0 {z['unidade']}")
            linhas.append("")

        if criticos:
            linhas.append("⚠️ **Materiais Próximos do Fim (Abaixo do Mínimo):**")
            for c in criticos[:5]:
                linhas.append(f"• {c.get('emoji','⚠️')} **{c['nome']}**: **{c['quantidade']} {c['unidade']}** (mínimo: {c['quantidade_minima']} {c['unidade']})")
            linhas.append("")
        else:
            linhas.append("✅ **Estoque de Insumos Saudável**: Todos os materiais estão acima do nível mínimo!")
            linhas.append("")

        linhas.append(f"🧾 **Pedidos em Andamento**: {len(pedidos_pendentes)} pedido(s) pendentes ou em produção.")

        msg = "📊 **Diagnóstico e Alertas do Ateliê:**\n\n" + "\n".join(linhas)
        voice = f"Diagnóstico do ateliê: temos {len(criticos)} materiais em nível crítico e {len(pedidos_pendentes)} pedidos em andamento."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos pendentes", "📄 Gerar PDF", "Consultar estoque"]}

    def _consultar_financeiro(self, p_clean: str) -> dict:
        pedidos = self.app.carregar_pedidos()
        despesas = self.app.carregar_despesas()

        receita_total = sum(float(p.get("valor_total") or 0) for p in pedidos if p.get("status") in ("Concluído", "Entregue"))
        receita_pendente = sum(float(p.get("valor_total") or 0) for p in pedidos if p.get("status") in ("Pendente", "Em produção"))
        despesa_total = sum(float(d.get("valor") or 0) for d in despesas)
        saldo_liquido = receita_total - despesa_total

        msg = (
            f"💰 **Resumo Financeiro do Ateliê**\n\n"
            f"• 📈 **Faturamento Realizado**: **{formatar_moeda(receita_total)}**\n"
            f"• ⏳ **Faturamento a Receber (Em produção)**: {formatar_moeda(receita_pendente)}\n"
            f"• 📉 **Total de Despesas**: **{formatar_moeda(despesa_total)}**\n"
            f"• 💵 **Saldo Líquido em Caixa**: **{formatar_moeda(saldo_liquido)}**\n\n"
            f"*{len(pedidos)} pedido(s) e {len(despesas)} despesa(s) registradas.*"
        )
        voice = f"O faturamento realizado é de {formatar_moeda(receita_total)}, com despesas de {formatar_moeda(despesa_total)}. O saldo líquido é de {formatar_moeda(saldo_liquido)}."
        return {"reply": msg, "voice_text": voice, "suggestions": ["📄 Enviar relatório em PDF", "Ver pedidos", "Cadastrar despesa"]}

    def _consultar_pedidos(self, p_clean: str) -> dict:
        pedidos = self.app.carregar_pedidos()
        if not pedidos:
            return {
                "reply": "🧾 Não há pedidos registrados no ateliê no momento.",
                "voice_text": "Não há pedidos registrados no momento.",
                "suggestions": ["➕ Criar novo pedido", "Ver produtos"]
            }

        pendentes = [p for p in pedidos if p.get("status") in ("Pendente", "Em produção")]
        concluidos = [p for p in pedidos if p.get("status") in ("Concluído", "Entregue")]

        if "pendente" in p_clean or "aberto" in p_clean or "producao" in p_clean:
            if not pendentes:
                return {
                    "reply": "🎉 Não há pedidos pendentes no momento! Todos os pedidos foram concluídos.",
                    "voice_text": "Não há pedidos pendentes.",
                    "suggestions": ["➕ Criar novo pedido", "Ver todos os pedidos"]
                }
            linhas = [f"• **{p['cliente']}**: {p['quantidade']}x {p['produto_emoji']} {p['produto_nome']} ({formatar_moeda(p['valor_total'])}) — Status: `{p['status']}`" for p in pendentes[:6]]
            msg = f"🧾 **Pedidos Pendentes e Em Produção ({len(pendentes)}):**\n\n" + "\n".join(linhas)
            voice = f"Temos {len(pendentes)} pedidos pendentes ou em produção no ateliê."
            return {"reply": msg, "voice_text": voice, "suggestions": ["➕ Criar novo pedido", "Concluir pedido", "Ver estoque"]}

        linhas = [f"• **{p['cliente']}**: {p['quantidade']}x {p['produto_emoji']} {p['produto_nome']} ({formatar_moeda(p['valor_total'])}) — `{p['status']}`" for p in pedidos[:5]]
        msg = (
            f"🧾 **Gestão de Pedidos do Ateliê**\n\n"
            f"• **Total de Pedidos**: {len(pedidos)} registros\n"
            f"• **Pendentes / Em Produção**: {len(pendentes)}\n"
            f"• **Concluídos / Entregues**: {len(concluidos)}\n\n"
            f"**Últimos Pedidos:**\n" + "\n".join(linhas)
        )
        voice = f"Temos {len(pedidos)} pedidos no total, sendo {len(pendentes)} pendentes e {len(concluidos)} concluídos."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos pendentes", "➕ Criar novo pedido", "📄 Gerar PDF"]}

    def _consultar_produtos(self, p_clean: str) -> dict:
        produtos = self.app.carregar_produtos()
        if not produtos:
            return {
                "reply": "👜 Não há produtos ou bolsas cadastradas ainda.",
                "voice_text": "Não há produtos cadastrados ainda.",
                "suggestions": ["➕ Cadastrar bolsa", "Consultar estoque"]
            }

        linhas = []
        voice_items = []
        for p in produtos:
            prontas = int(p.get("estoque_pronto") or 0)
            tag_pronta = f" · 🛍️ **{prontas} pronta(s)**" if prontas > 0 else " · *(Sob encomenda)*"
            linhas.append(f"• {p.get('emoji','👜')} **{p['nome']}**: {formatar_moeda(p['preco_venda'])}{tag_pronta}")
            voice_items.append(f"{p['nome']} por {formatar_moeda(p['preco_venda'])}")

        msg = f"👜 **Catálogo de Bolsas e Produtos ({len(produtos)}):**\n\n" + "\n".join(linhas)
        voice = "Temos as seguintes bolsas cadastradas: " + ", ".join(voice_items[:4]) + "."
        return {"reply": msg, "voice_text": voice, "suggestions": ["➕ Criar pedido", "Adicionar peças prontas", "Ver estoque"]}

    def _consultar_sobras(self) -> dict:
        sobras = self.app.carregar_sobras()
        if not sobras:
            return {
                "reply": "♻️ Não há retalhos ou sobras registrados no momento.",
                "voice_text": "Não há sobras ou retalhos registrados.",
                "suggestions": ["Cadastrar sobra", "Consultar estoque"]
            }

        disponiveis = [s for s in sobras if s.get("status") in ("Disponível", "Disponivel", None)]
        linhas = [f"• ✂️ **{s['descricao']}**: {s['quantidade']} {s['unidade']}" for s in disponiveis[:5]]

        msg = f"♻️ **Sobras e Retalhos Disponíveis ({len(disponiveis)}):**\n\n" + "\n".join(linhas)
        voice = f"Temos {len(disponiveis)} lotes de retalhos disponíveis para reaproveitamento."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Cadastrar sobra", "Consultar estoque"]}

    def _consultar_usuarios(self) -> dict:
        usuarios = self.app.carregar_usuarios()
        linhas = [f"• 👤 **{u.get('nome') or u['username']}** (`{u['username']}`) — Papel: `{u.get('role') or 'Colaborador'}`" for u in usuarios]
        msg = f"👥 **Usuários Cadastrados no Sistema ({len(usuarios)}):**\n\n" + "\n".join(linhas)
        voice = f"Existem {len(usuarios)} usuários cadastrados no sistema."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Minhas permissões", "Cadastrar usuário"]}
