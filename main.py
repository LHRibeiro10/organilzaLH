"""Bot do Telegram para controlar a caixinha da festa.

Lê mensagens em linguagem natural (ex.: "Fulano pagou 50"), interpreta a
intenção e lê/grava os dados em uma planilha do Google Sheets.
"""
import asyncio
import logging
import time
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from access_control import MENSAGEM_SEM_PERMISSAO, eh_organizador
from message_parser import Comando, interpretar_mensagem
from sheets_service import NUM_PARCELAS, PlanilhaError, SheetsService
from utils import formatar_moeda, normalizar, parse_valor

# janela de tempo dentro da qual um pagamento com mesmo nome+valor é tratado
# como possível duplicidade (ex.: usuário mandou a mensagem duas vezes por engano)
JANELA_DUPLICATA_SEGUNDOS = 120

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

planilha = SheetsService()

MENSAGEM_AJUDA = (
    "🧾 *Exemplos de mensagens que eu entendo:*\n\n"
    "*Registrar pagamento* (só organizadores)\n"
    "• Fulano pagou 50\n"
    "• Fulano pagou 50 reais\n"
    "• Fulano pagou R$ 50,00\n\n"
    "*Remover pagamento — corrigir engano* (só organizadores)\n"
    "• Fulano não pagou\n\n"
    "*Editar nome* (só organizadores)\n"
    "• Trocar nome Fulano para Fulano Silva\n\n"
    "*Cadastrar / remover participante* (só organizadores)\n"
    "• Adicionar participante Beltrano\n"
    "• Remover participante Beltrano\n\n"
    "*Definir meta* (só organizadores)\n"
    "• Definir meta 5000\n\n"
    "*Consultas* (qualquer pessoa no chat)\n"
    "• Quem já pagou?\n"
    "• Quem ainda não pagou?\n"
    "• Quanto Fulano pagou?\n"
    "• Quanto tem em caixa?\n"
    "• Quanto falta pra meta?\n"
    "• Resumo (ou /resumo)\n"
)


# ----------------------------------------------------------------- confirmações

def _solicitar_confirmacao(context: ContextTypes.DEFAULT_TYPE, user_id: int, tipo: str, dados: dict) -> str:
    """Guarda uma ação pendente de confirmação e retorna o token gerado."""
    pendentes = context.bot_data.setdefault("pendentes", {})
    token = uuid.uuid4().hex[:12]
    pendentes[token] = {"tipo": tipo, "dados": dados, "user_id": user_id}
    return token


def _teclado_confirmacao(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"ok:{token}"),
        InlineKeyboardButton("❌ Cancelar", callback_data=f"no:{token}"),
    ]])


def _chave_duplicata(chat_id: int, nome: str) -> str:
    return f"{chat_id}:{normalizar(nome)}"


def _eh_possivel_duplicata(context: ContextTypes.DEFAULT_TYPE, chat_id: int, nome: str, valor: float) -> bool:
    """True se esse mesmo nome+valor já foi registrado há pouco tempo (possível engano)."""
    registro = context.bot_data.get("ultimos_pagamentos", {}).get(_chave_duplicata(chat_id, nome))
    if not registro:
        return False
    valor_anterior, quando = registro
    return valor_anterior == valor and (time.monotonic() - quando) < JANELA_DUPLICATA_SEGUNDOS


def _marcar_pagamento_recente(context: ContextTypes.DEFAULT_TYPE, chat_id: int, nome: str, valor: float) -> None:
    context.bot_data.setdefault("ultimos_pagamentos", {})[_chave_duplicata(chat_id, nome)] = (valor, time.monotonic())


async def tratar_confirmacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa o clique nos botões Confirmar/Cancelar."""
    query = update.callback_query
    await query.answer()

    acao, _, token = query.data.partition(":")
    pendentes = context.bot_data.setdefault("pendentes", {})
    pendente = pendentes.pop(token, None)

    if pendente is None:
        await query.edit_message_text("⌛ Essa confirmação expirou ou já foi usada.")
        return

    if query.from_user.id != pendente["user_id"]:
        await query.answer("Só quem pediu a ação pode confirmar.", show_alert=True)
        pendentes[token] = pendente  # devolve para a fila, ainda não foi resolvida
        return

    if acao == "no":
        await query.edit_message_text("❌ Ação cancelada.")
        return

    tipo = pendente["tipo"]
    dados = pendente["dados"]
    chat_id = query.message.chat_id
    try:
        if tipo == "pagamento_novo_participante":
            planilha.adicionar_participante(dados["nome"])
            texto = _registrar_e_formatar(dados["nome"], dados["valor"])
            _marcar_pagamento_recente(context, chat_id, dados["nome"], dados["valor"])
        elif tipo == "pagamento_confirmar":
            texto = _registrar_e_formatar(dados["nome"], dados["valor"])
            _marcar_pagamento_recente(context, chat_id, dados["nome"], dados["valor"])
        elif tipo == "remover_participante":
            planilha.remover_participante(dados["nome"])
            texto = f"🗑️ {dados['nome']} foi removido da planilha."
        elif tipo == "remover_pagamento":
            texto = _remover_e_formatar(dados["nome"])
        else:
            texto = "Não sei mais o que fazer com essa confirmação."
    except PlanilhaError as exc:
        texto = f"📛 {exc}"

    await query.edit_message_text(texto)


def _registrar_e_formatar(nome: str, valor: float) -> str:
    """Registra o pagamento na próxima parcela vazia e monta a mensagem de sucesso."""
    novo_total, numero_parcela = planilha.registrar_pagamento(nome, valor)
    caixa = planilha.calcular_caixa()
    meta = planilha.obter_meta()
    faltam = max(meta - caixa, 0)
    return (
        f"✅ {nome} pagou {formatar_moeda(valor)} (parcela {numero_parcela}/{NUM_PARCELAS}). "
        f"Total dele: {formatar_moeda(novo_total)}. "
        f"Caixa: {formatar_moeda(caixa)} | Faltam {formatar_moeda(faltam)} pra meta."
    )


def _remover_e_formatar(nome: str) -> str:
    """Remove a parcela mais recente do participante e monta a mensagem de sucesso."""
    numero_parcela, valor, novo_total = planilha.remover_ultima_parcela(nome)
    caixa = planilha.calcular_caixa()
    meta = planilha.obter_meta()
    faltam = max(meta - caixa, 0)
    return (
        f"🗑️ Removido: parcela {numero_parcela} de {nome} ({formatar_moeda(valor)}). "
        f"Total dele agora: {formatar_moeda(novo_total)}. "
        f"Caixa: {formatar_moeda(caixa)} | Faltam {formatar_moeda(faltam)} pra meta."
    )


# ----------------------------------------------------------------- comandos de sistema

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Oi! Eu sou o bot da caixinha da festa.\n\n"
        "Eu controlo os pagamentos de cada participante numa planilha do Google Sheets. "
        "Você pode falar comigo em linguagem natural, tipo \"Fulano pagou 50\", ou usar comandos.\n\n"
        "Use /ajuda para ver todos os exemplos."
    )


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MENSAGEM_AJUDA, parse_mode="Markdown")


async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _enviar_resumo(update)


async def _enviar_resumo(update: Update) -> None:
    try:
        participantes = planilha.listar_participantes()
        caixa = planilha.calcular_caixa()
        meta = planilha.obter_meta()
    except PlanilhaError as exc:
        await update.message.reply_text(f"📛 {exc}")
        return

    comecaram = sum(1 for p in participantes if p["total"] > 0)
    nao_comecaram = len(participantes) - comecaram
    pct = (caixa / meta * 100) if meta else 0
    parcelas_pagas = sum(
        1 for p in participantes for v in p["parcelas"] if str(v).strip() != ""
    )
    parcelas_possiveis = len(participantes) * NUM_PARCELAS

    texto = (
        "📊 *Resumo da caixinha*\n\n"
        f"💰 Caixa atual: {formatar_moeda(caixa)}\n"
        f"🎯 Meta: {formatar_moeda(meta)}\n"
        f"📈 Atingido: {pct:.1f}%\n"
        f"✅ Já começaram a pagar: {comecaram}\n"
        f"❌ Ainda não pagaram nada: {nao_comecaram}\n"
        f"🧾 Parcelas pagas: {parcelas_pagas}/{parcelas_possiveis}"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


# ----------------------------------------------------------------- consultas (livres)

async def _quem_pagou(update: Update) -> None:
    participantes = planilha.listar_participantes()
    pagaram = [p for p in participantes if p["total"] > 0]
    if not pagaram:
        await update.message.reply_text("Ainda ninguém pagou nada. 😅")
        return
    pagaram.sort(key=lambda p: p["total"], reverse=True)
    largura_nome = max(len(p["nome"]) for p in pagaram)
    linhas = [
        f"{p['nome'].ljust(largura_nome)}  {formatar_moeda(p['total'])}" for p in pagaram
    ]
    texto = "✅ *Quem já pagou:*\n```\n" + "\n".join(linhas) + "\n```"
    await update.message.reply_text(texto, parse_mode="Markdown")


async def _quem_nao_pagou(update: Update) -> None:
    participantes = planilha.listar_participantes()
    nao_pagaram = [p for p in participantes if p["total"] <= 0]
    if not nao_pagaram:
        await update.message.reply_text("🎉 Todo mundo já contribuiu com alguma coisa!")
        return
    linhas = [p["nome"] for p in nao_pagaram]
    texto = "❌ *Ainda não pagaram nada:*\n```\n" + "\n".join(linhas) + "\n```"
    await update.message.reply_text(texto, parse_mode="Markdown")


async def _quanto_pessoa(update: Update, nome: str) -> None:
    participante = planilha.buscar_participante(nome)
    if not participante:
        await update.message.reply_text(f'🤷 Não encontrei "{nome}" na planilha.')
        return
    parcelas_pagas = sum(1 for v in participante["parcelas"] if str(v).strip() != "")
    await update.message.reply_text(
        f"{participante['nome']} já pagou {formatar_moeda(participante['total'])} "
        f"({parcelas_pagas}/{NUM_PARCELAS} parcelas)."
    )


async def _quanto_caixa(update: Update) -> None:
    caixa = planilha.calcular_caixa()
    await update.message.reply_text(f"💰 Tem {formatar_moeda(caixa)} em caixa.")


async def _quanto_falta(update: Update) -> None:
    caixa = planilha.calcular_caixa()
    meta = planilha.obter_meta()
    if caixa >= meta:
        await update.message.reply_text(f"🎉 Meta de {formatar_moeda(meta)} já atingida!")
        return
    await update.message.reply_text(f"📉 Faltam {formatar_moeda(meta - caixa)} pra bater a meta de {formatar_moeda(meta)}.")


# ----------------------------------------------------------------- ações restritas

async def _pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict) -> None:
    nome = dados["nome"]
    try:
        valor = parse_valor(dados["valor_texto"])
    except ValueError:
        await update.message.reply_text(
            f'🤔 Não consegui entender o valor "{dados["valor_texto"]}". Tente algo como "50" ou "50,00".'
        )
        return

    participante = planilha.buscar_participante(nome)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if participante is None:
        token = _solicitar_confirmacao(
            context, user_id, "pagamento_novo_participante", {"nome": nome, "valor": valor}
        )
        await update.message.reply_text(
            f'🆕 "{nome}" não está cadastrado ainda. Quer cadastrar e já registrar o pagamento de '
            f"{formatar_moeda(valor)}?",
            reply_markup=_teclado_confirmacao(token),
        )
        return

    parcelas_preenchidas = sum(1 for v in participante["parcelas"] if str(v).strip() != "")
    if parcelas_preenchidas >= NUM_PARCELAS:
        await update.message.reply_text(
            f"🙌 {participante['nome']} já quitou as {NUM_PARCELAS} parcelas. "
            "Não há parcela livre pra registrar esse pagamento."
        )
        return

    motivos = []
    if valor > config.VALOR_CONFIRMACAO:
        motivos.append(f"é um valor alto (acima de {formatar_moeda(config.VALOR_CONFIRMACAO)})")
    if _eh_possivel_duplicata(context, chat_id, nome, valor):
        motivos.append("você registrou esse mesmo valor pra essa pessoa há pouco tempo (possível duplicidade)")

    if motivos:
        token = _solicitar_confirmacao(context, user_id, "pagamento_confirmar", {"nome": nome, "valor": valor})
        razao = " e ".join(motivos)
        await update.message.reply_text(
            f"⚠️ Confirma o pagamento de {formatar_moeda(valor)} para {participante['nome']}? "
            f"({razao})",
            reply_markup=_teclado_confirmacao(token),
        )
        return

    await update.message.reply_text(_registrar_e_formatar(nome, valor))
    _marcar_pagamento_recente(context, chat_id, nome, valor)


async def _renomear(update: Update, dados: dict) -> None:
    planilha.renomear_participante(dados["nome_atual"], dados["nome_novo"])
    await update.message.reply_text(f"✏️ Nome atualizado: {dados['nome_atual']} → {dados['nome_novo']}")


async def _adicionar_participante(update: Update, dados: dict) -> None:
    planilha.adicionar_participante(dados["nome"])
    await update.message.reply_text(f"➕ {dados['nome']} foi adicionado à planilha.")


async def _remover_participante(update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict) -> None:
    nome = dados["nome"]
    if not planilha.buscar_participante(nome):
        await update.message.reply_text(f'🤷 Não encontrei "{nome}" na planilha.')
        return
    token = _solicitar_confirmacao(context, update.effective_user.id, "remover_participante", {"nome": nome})
    await update.message.reply_text(
        f'⚠️ Tem certeza que quer remover "{nome}" da planilha? Essa ação não pode ser desfeita.',
        reply_markup=_teclado_confirmacao(token),
    )


async def _remover_pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict) -> None:
    nome = dados["nome"]
    # localiza a parcela mais recente só pra montar a mensagem de confirmação;
    # a remoção de fato só acontece se o organizador clicar em ✅.
    numero_parcela, valor = planilha.localizar_ultima_parcela(nome)
    participante = planilha.buscar_participante(nome)
    token = _solicitar_confirmacao(
        context, update.effective_user.id, "remover_pagamento",
        {"nome": participante["nome"]},
    )
    await update.message.reply_text(
        f"⚠️ Remover a parcela {numero_parcela} de {participante['nome']} "
        f"({formatar_moeda(valor)})? Isso vai zerar esse pagamento.",
        reply_markup=_teclado_confirmacao(token),
    )


async def _definir_meta(update: Update, dados: dict) -> None:
    try:
        valor = parse_valor(dados["valor_texto"])
    except ValueError:
        await update.message.reply_text(f'🤔 Não consegui entender o valor "{dados["valor_texto"]}".')
        return
    planilha.definir_meta(valor)
    await update.message.reply_text(f"🎯 Meta definida: {formatar_moeda(valor)}")


# ----------------------------------------------------------------- roteamento principal

ACOES_RESTRITAS = {
    "pagamento",
    "remover_pagamento",
    "renomear",
    "adicionar_participante",
    "remover_participante",
    "definir_meta",
}


async def tratar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    comando: Comando = interpretar_mensagem(update.message.text)

    if comando.tipo is None:
        await update.message.reply_text(
            "🤔 Não entendi essa mensagem. Veja exemplos com /ajuda."
        )
        return

    if comando.tipo in ACOES_RESTRITAS and not eh_organizador(update.effective_user.id):
        await update.message.reply_text(MENSAGEM_SEM_PERMISSAO)
        return

    try:
        if comando.tipo == "pagamento":
            await _pagamento(update, context, comando.dados)
        elif comando.tipo == "renomear":
            await _renomear(update, comando.dados)
        elif comando.tipo == "adicionar_participante":
            await _adicionar_participante(update, comando.dados)
        elif comando.tipo == "remover_participante":
            await _remover_participante(update, context, comando.dados)
        elif comando.tipo == "remover_pagamento":
            await _remover_pagamento(update, context, comando.dados)
        elif comando.tipo == "definir_meta":
            await _definir_meta(update, comando.dados)
        elif comando.tipo == "quem_pagou":
            await _quem_pagou(update)
        elif comando.tipo == "quem_nao_pagou":
            await _quem_nao_pagou(update)
        elif comando.tipo == "quanto_pessoa":
            await _quanto_pessoa(update, comando.dados["nome"])
        elif comando.tipo == "quanto_caixa":
            await _quanto_caixa(update)
        elif comando.tipo == "quanto_falta":
            await _quanto_falta(update)
        elif comando.tipo == "resumo":
            await _enviar_resumo(update)
    except PlanilhaError as exc:
        await update.message.reply_text(f"📛 {exc}")


async def tratar_erro(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Erro não tratado: %s", context.error, exc_info=context.error)


def main() -> None:
    config.validar_configuracao()

    # No Python 3.14, a thread principal não tem mais um event loop criado
    # automaticamente; garantimos um aqui antes do run_polling() criar o dele.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CallbackQueryHandler(tratar_confirmacao))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tratar_mensagem))
    app.add_error_handler(tratar_erro)

    logger.info("Bot iniciado, aguardando mensagens (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
