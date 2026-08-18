"""
ania_assistant.py - Motor Inteligente do Chatbot Ania para Ateliê Haiti
Assistente com suporte a comandos por texto e voz, execução de ações e verificação rigorosa de RBAC.
100% gratuito, sem dependências de APIs pagas.
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
        Processa a mensagem do usuário (texto ou fala transcrita), valida o nível de acesso (RBAC)
        e executa a ação/consulta solicitada.
        """
        if not prompt or not prompt.strip():
            return {
                "reply": "Olá! Estou ouvindo. Como posso te ajudar hoje no ateliê?",
                "voice_text": "Olá! Estou ouvindo. Como posso te ajudar hoje no ateliê?",
                "suggestions": ["📦 Consultar estoque", "🧾 Pedidos pendentes", "📊 Ver alertas", "💰 Resumo financeiro"],
            }

        prompt_orig = prompt.strip()
        p_clean = remover_acentos(prompt_orig)
        user_nome = user.get("nome") or user.get("username") or "Artesã(o)"
        roles = self.app.usuario_roles_lista(user)
        roles_str = ", ".join(roles) if roles else "Colaborador"

        # ── 1. SAUDAÇÃO & AJUDA ───────────────────────────────────────────────
        if any(w in p_clean for w in ["quem e voce", "o que voce faz", "ajuda", "comandos", "menu", "como usar"]) or p_clean in ["ola", "oi", "bom dia", "boa tarde", "boa noite", "ania"]:
            return self._responder_ajuda(user_nome, roles)

        # ── 2. CONSULTAR PERMISSÕES / MEU PERFIL ──────────────────────────────
        if any(w in p_clean for w in ["minhas permissoes", "meu perfil", "meu papel", "o que posso fazer", "meus acessos"]):
            return self._responder_minhas_permissoes(user, user_nome, roles)

        # ── 3. NAVEGAÇÃO RÁPIDA ───────────────────────────────────────────────
        nav_match = self._verificar_navegacao(p_clean)
        if nav_match:
            recurso, url_dest, nome_tela = nav_match
            if not self._tem_permissao(user, recurso, "read") and not self._tem_permissao(user, recurso, "create"):
                return self._resposta_negada(user_nome, roles_str, recurso, "read", f"navegar até a página de {nome_tela}")
            return {
                "reply": f"🧭 Abrindo a página de **{nome_tela}** para você...",
                "voice_text": f"Abrindo a página de {nome_tela}.",
                "action": {"type": "navigate", "url": url_dest},
                "suggestions": ["Voltar ao início", "Consultar estoque", "Ver pedidos"],
            }

        # ── 4. AÇÕES DE PEDIDOS: CRIAR NOVO PEDIDO ────────────────────────────
        if any(w in p_clean for w in ["criar pedido", "novo pedido", "adicionar pedido", "fazer pedido", "registrar pedido"]):
            if not self._tem_permissao(user, "pedidos", "create"):
                return self._resposta_negada(user_nome, roles_str, "pedidos", "create", "criar novos pedidos de clientes")
            return self._executar_criar_pedido(p_clean, prompt_orig, user)

        # ── 5. AÇÕES DE ESTOQUE: DAR BAIXA DE INSUMOS ─────────────────────────
        if any(p_clean.startswith(w) for w in ["dar baixa", "baixar", "usei", "consumi", "gastei", "retirar do estoque"]) or "dar baixa" in p_clean:
            if not self._tem_permissao(user, "baixa", "create"):
                return self._resposta_negada(user_nome, roles_str, "baixa", "create", "dar baixa de insumos no estoque")
            return self._executar_dar_baixa(p_clean, prompt_orig, user)

        # ── 6. ALERTAS & RESUMO EXECUTIVO ─────────────────────────────────────
        if any(w in p_clean for w in ["alerta", "alertas", "estoque baixo", "acabando", "abaixo do minimo", "resumo do atelier", "diagnostico"]):
            if not self._tem_permissao(user, "relatorios", "read"):
                return self._resposta_negada(user_nome, roles_str, "relatorios", "read", "visualizar alertas e relatórios de desempenho")
            return self._consultar_alertas_e_resumo()

        # ── 7. CONSULTAR FINANCEIRO (RECEITAS, DESPESAS, FATURAMENTO) ─────────
        if any(w in p_clean for w in ["financeiro", "saldo", "faturamento", "receita", "despesa", "lucro", "caixa", "faturamos", "ganhos"]):
            if not self._tem_permissao(user, "financeiro", "read"):
                return self._resposta_negada(user_nome, roles_str, "financeiro", "read", "consultar dados financeiros e faturamento")
            return self._consultar_financeiro(p_clean)

        # ── 8. CONSULTAR PEDIDOS DE CLIENTES ──────────────────────────────────
        if any(w in p_clean for w in ["pedido", "pedidos", "encomenda", "encomendas"]):
            if not self._tem_permissao(user, "pedidos", "read"):
                return self._resposta_negada(user_nome, roles_str, "pedidos", "read", "visualizar a lista de pedidos de clientes")
            return self._consultar_pedidos(p_clean)

        # ── 9. CONSULTAR PRODUTOS & BOLSAS ────────────────────────────────────
        if any(w in p_clean for w in ["bolsa", "bolsas", "produto", "produtos", "receita da bolsa", "preco da bolsa", "pronta entrega"]):
            if not self._tem_permissao(user, "produtos", "read"):
                return self._resposta_negada(user_nome, roles_str, "produtos", "read", "consultar catálogo de produtos e receitas")
            return self._consultar_produtos(p_clean)

        # ── 10. CONSULTAR SOBRAS & RETALHOS ───────────────────────────────────
        if any(w in p_clean for w in ["sobra", "sobras", "retalho", "retalhos", "reaproveitamento"]):
            if not self._tem_permissao(user, "sobras", "read"):
                return self._resposta_negada(user_nome, roles_str, "sobras", "read", "consultar sobras e retalhos")
            return self._consultar_sobras()

        # ── 11. CONSULTAR ESTOQUE GERAL OU MATERIAL ESPECÍFICO ────────────────
        if any(w in p_clean for w in ["estoque", "material", "materiais", "quanto temos", "quantidade de", "insumo", "insumos", "gtin"]) or self._busca_material_direta(p_clean):
            if not self._tem_permissao(user, "estoque", "read"):
                return self._resposta_negada(user_nome, roles_str, "estoque", "read", "consultar materiais e quantidades em estoque")
            return self._consultar_estoque(p_clean, prompt_orig)

        # ── 12. CONSULTAR USUÁRIOS ────────────────────────────────────────────
        if any(w in p_clean for w in ["usuario", "usuarios", "quem tem acesso", "listar usuarios"]):
            if not self._tem_permissao(user, "usuarios", "read"):
                return self._resposta_negada(user_nome, roles_str, "usuarios", "read", "visualizar usuários do sistema")
            return self._consultar_usuarios()

        # ── FALLBACK INTELIGENTE ──────────────────────────────────────────────
        return {
            "reply": f"Entendi sua mensagem, **{user_nome}**, mas ainda não tenho certeza exata de qual ação executar. Veja algumas opções rápidas que você pode me pedir:",
            "voice_text": f"Não compreendi totalmente. Escolha uma das opções abaixo ou tente reformular sua pergunta.",
            "suggestions": [
                "📦 Quanto couro temos?",
                "🧾 Listar pedidos pendentes",
                "📊 Quais alertas temos?",
                "💰 Qual o faturamento?",
                "✂️ Dar baixa de zíper",
                "Minhas permissões"
            ],
        }

    # ── HELPERS DE VERIFICAÇÃO DE PERMISSÃO (RBAC) ───────────────────────────

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

    # ── MÉTODOS DE PROCESSAMENTO E CONSULTAS ─────────────────────────────────

    def _responder_ajuda(self, user_nome: str, roles: list) -> dict:
        msg = (
            f"✨ **Olá, {user_nome}! Eu sou a Ania**, sua assistente inteligente do Ateliê Haiti. 🧵\n\n"
            f"Você pode falar comigo por **voz (clicando no microfone 🎙️)** ou **digitando**, e eu executo as tarefas respeitando suas permissões ({', '.join(roles) if roles else 'Colaborador'}).\n\n"
            f"**Exemplos do que você pode me pedir:**\n"
            f"• 📦 *\"Quanto temos de couro em estoque?\"*\n"
            f"• ✂️ *\"Dar baixa de 2 zíperes por costura\"*\n"
            f"• 🧾 *\"Criar pedido para Maria Silva da Bolsa Tote\"*\n"
            f"• 📊 *\"Quais materiais estão com estoque baixo?\"*\n"
            f"• 💰 *\"Qual o faturamento e saldo do financeiro?\"*\n"
            f"• 👜 *\"Quantas bolsas prontas temos no estoque?\"*\n"
            f"• 🔒 *\"Quais são as minhas permissões?\"*\n"
            f"• 🧭 *\"Ir para a página de pedidos\"*"
        )
        voice = f"Olá {user_nome}! Eu sou a Ania, assistente do ateliê. Você pode me pedir para consultar o estoque, dar baixa em materiais, registrar pedidos ou verificar o financeiro por voz ou texto."
        return {
            "reply": msg,
            "voice_text": voice,
            "suggestions": ["📦 Consultar estoque", "🧾 Pedidos pendentes", "📊 Ver alertas", "💰 Resumo financeiro", "Minhas permissões"]
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
            f"👤 **Perfil de Acesso de {user_nome}**\n\n"
            f"• **Papéis Ativos**: `{roles_str}`\n"
            f"• **Nível**: {'👑 Administrador (Acesso Total)' if is_admin else '🧵 Usuário Padrão com Permissões Específicas'}\n\n"
            f"📋 **Módulos que você pode acessar:**\n" +
            ("\n".join([f"• {t}" for t in tabs_permitidas]) if tabs_permitidas else "• *Nenhum módulo liberado atualmente.*")
        )
        voice = f"{user_nome}, seu perfil possui os papéis: {roles_str}. Você tem acesso a {len(tabs_permitidas)} módulos do ateliê."
        return {
            "reply": msg,
            "voice_text": voice,
            "suggestions": ["📦 Consultar estoque", "🧾 Pedidos", "📊 Alertas", "Voltar ao início"]
        }

    def _verificar_navegacao(self, p_clean: str):
        rotas = [
            (["ir para estoque", "abrir estoque", "me leve para o estoque", "tela de estoque"], "estoque", "/estoque", "Estoque"),
            (["ir para adicionar", "adicionar material", "cadastrar material", "tela de adicionar"], "adicionar", "/adicionar", "Adicionar Material"),
            (["ir para baixa", "abrir baixa", "tela de baixa", "dar baixa manual"], "baixa", "/baixa", "Dar Baixa"),
            (["ir para produtos", "abrir produtos", "catalogo de bolsas", "tela de produtos"], "produtos", "/produtos", "Produtos & Receitas"),
            (["ir para pedidos", "abrir pedidos", "tela de pedidos", "listar pedidos"], "pedidos", "/pedidos", "Pedidos dos Clientes"),
            (["ir para sobras", "abrir sobras", "tela de sobras", "ver retalhos"], "sobras", "/sobras", "Sobras & Reaproveitamento"),
            (["ir para financeiro", "abrir financeiro", "tela de financeiro"], "financeiro", "/financeiro", "Financeiro"),
            (["ir para alertas", "abrir alertas", "ir para relatorios", "abrir relatorios"], "relatorios", "/alertas", "Alertas e Relatórios"),
            (["ir para usuarios", "abrir usuarios", "tela de usuarios"], "usuarios", "/usuarios", "Gestão de Usuários"),
            (["ir para papeis", "abrir papeis", "abrir permissoes"], "roles", "/roles", "Papéis & Permissões"),
            (["minha conta", "meu perfil", "editar perfil"], "estoque", "/minha-conta", "Minha Conta"),
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
                "suggestions": ["➕ Adicionar Material", "Ver produtos"]
            }

        # Verifica se busca por GTIN
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
                return {"reply": msg, "voice_text": voice, "suggestions": ["Dar baixa deste material", "Ver todos materiais"]}

        # Verifica se busca material específico pelo nome
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
                status_alerta = " ⚠️ *(Abaixo do mínimo!)*" if qtd <= qtd_min else " ✅ *(Estoque normal)*"
                linhas.append(
                    f"• {m.get('emoji','📦')} **{m['nome']}**: **{m['quantidade']} {m['unidade']}** (Custo: {formatar_moeda(m['custo'])}){status_alerta}"
                )
                voice_parts.append(f"{m['nome']}: {m['quantidade']} {m['unidade']}")

            msg = "📦 **Consulta de Estoque:**\n\n" + "\n".join(linhas)
            voice = "Temos em estoque: " + ", ".join(voice_parts) + "."
            return {"reply": msg, "voice_text": voice, "suggestions": ["Dar baixa", "Ver alertas de estoque", "Resumo financeiro"]}

        # Visão Geral do Estoque
        total_itens = len(materiais)
        qtd_total = sum(float(m.get("quantidade") or 0) for m in materiais)
        valor_total = sum(float(m.get("quantidade") or 0) * float(m.get("custo") or 0) for m in materiais)
        abaixo_min = [m for m in materiais if float(m.get("quantidade") or 0) <= float(m.get("quantidade_minima") or 0)]

        msg = (
            f"📦 **Visão Geral do Estoque do Ateliê**\n\n"
            f"• **Materiais Cadastrados**: {total_itens} insumos diferentes\n"
            f"• **Valor Total em Estoque**: **{formatar_moeda(valor_total)}**\n"
            f"• **Itens com Alerta (Abaixo do Mínimo)**: {len(abaixo_min)} item(ns)\n\n"
            f"Para consultar um material específico, você pode me perguntar: *\"Quanto couro temos?\"* ou *\"Qual o estoque de zíper?\"*."
        )
        voice = f"O estoque possui {total_itens} materiais cadastrados, somando {formatar_moeda(valor_total)}. Temos {len(abaixo_min)} itens abaixo do estoque mínimo."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Quais itens estão acabando?", "Consultar couro", "Dar baixa"]}

    def _consultar_alertas_e_resumo(self) -> dict:
        materiais = self.app.carregar_materiais()
        pedidos = self.app.carregar_pedidos()
        produtos = self.app.carregar_produtos()

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
            linhas.append("⚠️ **Materiais Próximos do Fim (Abaixo da Qtd Mínima):**")
            for c in criticos[:5]:
                linhas.append(f"• {c.get('emoji','⚠️')} **{c['nome']}**: **{c['quantidade']} {c['unidade']}** (mínimo recomendado: {c['quantidade_minima']} {c['unidade']})")
            linhas.append("")
        else:
            linhas.append("✅ **Estoque de Insumos Saudável**: Todos os materiais estão acima do nível mínimo!")
            linhas.append("")

        linhas.append(f"🧾 **Pedidos em Andamento**: {len(pedidos_pendentes)} pedido(s) aguardando confecção ou entrega.")

        msg = "📊 **Diagnóstico e Alertas do Ateliê:**\n\n" + "\n".join(linhas)
        voice = f"Diagnóstico do ateliê: temos {len(criticos)} materiais em nível crítico de estoque e {len(pedidos_pendentes)} pedidos em andamento."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos pendentes", "Consultar estoque", "Abrir relatórios"]}

    def _consultar_financeiro(self, p_clean: str) -> dict:
        pedidos = self.app.carregar_pedidos()
        despesas = self.app.carregar_despesas()

        # Receita total de pedidos concluídos ou entregues
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
            f"*{len(pedidos)} pedido(s) faturados e {len(despesas)} despesa(s) registradas.*"
        )
        voice = f"O faturamento realizado é de {formatar_moeda(receita_total)}, com despesas de {formatar_moeda(despesa_total)}. O saldo líquido atual é de {formatar_moeda(saldo_liquido)}."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos", "Abrir tela do financeiro", "Consultar estoque"]}

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
                    "voice_text": "Não há pedidos pendentes. Todos os pedidos já foram concluídos.",
                    "suggestions": ["➕ Criar novo pedido", "Ver todos os pedidos"]
                }
            linhas = []
            for p in pendentes[:6]:
                linhas.append(f"• **{p['cliente']}**: {p['quantidade']}x {p['produto_emoji']} {p['produto_nome']} ({formatar_moeda(p['valor_total'])}) — Status: `{p['status']}`")
            msg = f"🧾 **Pedidos Pendentes e Em Produção ({len(pendentes)}):**\n\n" + "\n".join(linhas)
            voice = f"Temos {len(pendentes)} pedidos pendentes ou em produção no ateliê."
            return {"reply": msg, "voice_text": voice, "suggestions": ["➕ Criar novo pedido", "Abrir pedidos", "Ver estoque"]}

        # Listagem Geral
        linhas = []
        for p in pedidos[:5]:
            linhas.append(f"• **{p['cliente']}**: {p['quantidade']}x {p['produto_emoji']} {p['produto_nome']} ({formatar_moeda(p['valor_total'])}) — `{p['status']}`")

        msg = (
            f"🧾 **Gestão de Pedidos do Ateliê**\n\n"
            f"• **Total de Pedidos**: {len(pedidos)} registros\n"
            f"• **Pendentes / Em Produção**: {len(pendentes)}\n"
            f"• **Concluídos / Entregues**: {len(concluidos)}\n\n"
            f"**Últimos Pedidos:**\n" + "\n".join(linhas)
        )
        voice = f"Temos {len(pedidos)} pedidos no total, sendo {len(pendentes)} pendentes e {len(concluidos)} concluídos."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Ver pedidos pendentes", "➕ Criar novo pedido", "Consultar estoque"]}

    def _consultar_produtos(self, p_clean: str) -> dict:
        produtos = self.app.carregar_produtos()
        if not produtos:
            return {
                "reply": "👜 Não há produtos ou bolsas cadastradas ainda.",
                "voice_text": "Não há produtos cadastrados ainda.",
                "suggestions": ["➕ Cadastrar Produto", "Consultar estoque"]
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
        return {"reply": msg, "voice_text": voice, "suggestions": ["➕ Criar pedido", "Ver estoque", "Alertas"]}

    def _consultar_sobras(self) -> dict:
        sobras = self.app.carregar_sobras()
        if not sobras:
            return {
                "reply": "♻️ Não há retalhos ou sobras registrados no momento.",
                "voice_text": "Não há sobras ou retalhos registrados.",
                "suggestions": ["Consultar estoque", "Ver produtos"]
            }

        disponiveis = [s for s in sobras if s.get("status") in ("Disponível", "Disponivel", None)]
        linhas = []
        for s in disponiveis[:5]:
            linhas.append(f"• ✂️ **{s['descricao']}**: {s['quantidade']} {s['unidade']}")

        msg = f"♻️ **Sobras e Retalhos Disponíveis ({len(disponiveis)}):**\n\n" + "\n".join(linhas)
        voice = f"Temos {len(disponiveis)} lotes de retalhos disponíveis para reaproveitamento."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Consultar estoque", "Ver pedidos"]}

    def _consultar_usuarios(self) -> dict:
        usuarios = self.app.carregar_usuarios()
        linhas = []
        for u in usuarios:
            r = u.get("role") or "Colaborador"
            linhas.append(f"• 👤 **{u.get('nome') or u['username']}** (`{u['username']}`) — Papel: `{r}`")

        msg = f"👥 **Usuários Cadastrados no Sistema ({len(usuarios)}):**\n\n" + "\n".join(linhas)
        voice = f"Existem {len(usuarios)} usuários cadastrados no sistema."
        return {"reply": msg, "voice_text": voice, "suggestions": ["Minhas permissões", "Consultar estoque"]}

    # ── EXECUÇÃO DE AÇÕES DIRETAS (DAR BAIXA E CRIAR PEDIDO) ─────────────────

    def _executar_dar_baixa(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        materiais = self.app.carregar_materiais()
        if not materiais:
            return {"reply": "Não há materiais no estoque para dar baixa.", "voice_text": "Estoque vazio."}

        # Extrair quantidade numérica
        match_qtd = re.search(r"(\d+(?:[.,]\d+)?)", p_clean)
        qtd = float(match_qtd.group(1).replace(",", ".")) if match_qtd else 1.0

        # Encontrar material correspondente
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

        # Extrair motivo
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
            movs = self.app.carregar_movimentacoes()
            movs.insert(0, {
                "id": str(uuid.uuid4()),
                "tipo": "saida",
                "material_nome": material_alvo["nome"],
                "quantidade": qtd,
                "unidade": material_alvo["unidade"],
                "motivo": f"{motivo} (Assistente Ania)",
                "data": dt_str,
                "usuario": user_id,
            })
            self.app.salvar_json("movimentacoes.json", movs)

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

    def _executar_criar_pedido(self, p_clean: str, prompt_orig: str, user: dict) -> dict:
        produtos = self.app.carregar_produtos()
        if not produtos:
            return {"reply": "Não há bolsas ou produtos cadastrados para registrar pedidos.", "voice_text": "Não há produtos cadastrados."}

        # Extrair quantidade
        match_qtd = re.search(r"(\d+)\s*(?:unidades?|pecas?|bolsas?|x)?", p_clean)
        qtd = int(match_qtd.group(1)) if match_qtd else 1

        # Encontrar bolsa / produto
        produto_alvo = None
        for p in produtos:
            p_nome_clean = remover_acentos(p["nome"])
            if p_nome_clean in p_clean or any(palavra in p_clean for palavra in p_nome_clean.split() if len(palavra) >= 4):
                produto_alvo = p
                break

        # Extrair nome do cliente se mencionado (ex: "para Maria Silva", "cliente Joao")
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

        # Verifica pronta entrega
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
            f"O pedido já está registrado no sistema."
        )
        voice = f"Pedido de {qtd} {produto_alvo['nome']} para {cliente} registrado com sucesso no valor de {formatar_moeda(valor_total)}."
        return {
            "success": True,
            "reply": msg,
            "voice_text": voice,
            "action": {"type": "refresh_or_notify", "pedido_id": novo_pedido["id"]},
            "suggestions": ["Ver pedidos pendentes", "Consultar estoque", "Resumo financeiro"]
        }
