"""Camada de acesso à planilha do Google Sheets.

A aba de pagamentos (nome configurável via SHEET_ABA_PAGAMENTOS) já existe
com uma estrutura própria de parcelas:

    Linhas 2-5: cabeçalho mesclado ("CONFRATERNIZAÇÃO 2026", "PARCELAS" etc.) — ignoradas.
    Coluna B:        nome do participante.
    Colunas C..N:    parcelas 1 a 12 (uma coluna por parcela).
    Coluna O:        total do participante (pode ser fórmula =SOMA(...); nunca sobrescrita
                      enquanto for fórmula).
    Linha "TOTAL":   linha de total geral (coluna B = "TOTAL"); nunca tratada como participante.

A aba "Config" (chave/valor, com a linha "meta") é criada automaticamente
se ainda não existir.
"""
from threading import Lock

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption, ValueRenderOption

import config
from utils import col_letra, normalizar

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# --- layout fixo da aba de parcelas ---
COL_NOME = 2  # B
COL_PRIMEIRA_PARCELA = 3  # C
NUM_PARCELAS = 12
COL_ULTIMA_PARCELA = COL_PRIMEIRA_PARCELA + NUM_PARCELAS - 1  # N (14)
COL_TOTAL = COL_ULTIMA_PARCELA + 1  # O (15)

CONFIG_CABECALHO = ["Chave", "Valor"]


class PlanilhaError(Exception):
    """Erro genérico de comunicação com a planilha (rede, permissão, dados ausentes etc.)."""


class SheetsService:
    def __init__(self) -> None:
        # trava simples para não gravar duas células ao mesmo tempo se duas mensagens
        # chegarem em paralelo
        self._lock = Lock()
        try:
            credenciais = Credentials.from_service_account_file(
                config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
            )
            cliente = gspread.authorize(credenciais)
            if config.GOOGLE_SHEET_ID:
                planilha = cliente.open_by_key(config.GOOGLE_SHEET_ID)
            else:
                planilha = cliente.open(config.GOOGLE_SHEET_NAME)
        except Exception as exc:  # falha de auth/rede/planilha inexistente
            raise PlanilhaError(f"Não foi possível conectar à planilha: {exc}") from exc

        try:
            self._aba_pagamentos = planilha.worksheet(config.SHEET_ABA_PAGAMENTOS)
        except gspread.exceptions.WorksheetNotFound as exc:
            raise PlanilhaError(
                f'Aba "{config.SHEET_ABA_PAGAMENTOS}" não encontrada. '
                "Confira o valor de SHEET_ABA_PAGAMENTOS no .env."
            ) from exc

        self._aba_config = self._obter_ou_criar_aba_config(planilha)

    def _obter_ou_criar_aba_config(self, planilha: gspread.Spreadsheet):
        try:
            return planilha.worksheet(config.SHEET_ABA_CONFIG)
        except gspread.exceptions.WorksheetNotFound:
            try:
                aba = planilha.add_worksheet(title=config.SHEET_ABA_CONFIG, rows=10, cols=2)
                aba.append_row(CONFIG_CABECALHO)
                aba.append_row(["meta", config.META_PADRAO])
                return aba
            except Exception as exc:
                raise PlanilhaError(f'Erro ao criar a aba "{config.SHEET_ABA_CONFIG}": {exc}') from exc

    # ---------------------------------------------------------------- leitura do bloco de dados

    def _ler_bloco(self) -> tuple[list[dict], int | None]:
        """Lê o bloco de participantes (colunas Nome..Total) numa única chamada.

        Detecta dinamicamente a última linha com dados e a linha de TOTAL geral
        (coluna B = "TOTAL"), que é excluída da lista de participantes.
        """
        try:
            coluna_nomes = self._aba_pagamentos.col_values(COL_NOME)
        except Exception as exc:
            raise PlanilhaError(f"Erro ao ler a planilha: {exc}") from exc

        ultima_linha = len(coluna_nomes)
        if ultima_linha < config.LINHA_INICIAL:
            return [], None

        intervalo = (
            f"{col_letra(COL_NOME)}{config.LINHA_INICIAL}:"
            f"{col_letra(COL_TOTAL)}{ultima_linha}"
        )
        try:
            linhas = self._aba_pagamentos.get(intervalo, value_render_option=ValueRenderOption.unformatted)
        except Exception as exc:
            raise PlanilhaError(f"Erro ao ler a planilha: {exc}") from exc

        participantes = []
        linha_total = None
        for deslocamento, valores in enumerate(linhas):
            linha = config.LINHA_INICIAL + deslocamento
            nome = str(valores[0]).strip() if valores else ""
            if not nome:
                continue
            if normalizar(nome) == "total":
                linha_total = linha
                continue

            parcelas = [valores[i] if i < len(valores) else "" for i in range(1, NUM_PARCELAS + 1)]
            total_bruto = valores[NUM_PARCELAS + 1] if len(valores) > NUM_PARCELAS + 1 else ""
            if str(total_bruto).strip() != "":
                total = self._para_float(total_bruto)
            else:
                total = sum(self._para_float(p) for p in parcelas)

            participantes.append({
                "linha": linha,
                "nome": nome,
                "parcelas": parcelas,
                "total": total,
            })

        return participantes, linha_total

    def listar_participantes(self) -> list[dict]:
        participantes, _ = self._ler_bloco()
        return participantes

    def buscar_participante(self, nome: str) -> dict | None:
        """Busca participante por nome, ignorando acentuação e diferenças de caixa."""
        alvo = normalizar(nome)
        for participante in self.listar_participantes():
            if normalizar(participante["nome"]) == alvo:
                return participante
        return None

    # ---------------------------------------------------------------- cadastro / edição

    def adicionar_participante(self, nome: str) -> None:
        if self.buscar_participante(nome):
            raise PlanilhaError(f'"{nome}" já está cadastrado na planilha.')

        participantes, linha_total = self._ler_bloco()
        linha_em_branco = [""] * COL_TOTAL  # colunas A..O, A fica vazia (não é usada)
        linha_em_branco[COL_NOME - 1] = nome

        with self._lock:
            try:
                if linha_total is not None:
                    # insere a nova linha bem acima da linha de TOTAL geral, empurrando-a pra baixo
                    self._aba_pagamentos.insert_row(
                        linha_em_branco,
                        index=linha_total,
                        value_input_option=ValueInputOption.user_entered,
                        inherit_from_before=True,
                    )
                else:
                    # não há linha de TOTAL visível: simplesmente acrescenta após o último participante
                    ultima = participantes[-1]["linha"] if participantes else config.LINHA_INICIAL - 1
                    intervalo = (
                        f"{col_letra(COL_NOME)}{ultima + 1}:{col_letra(COL_TOTAL)}{ultima + 1}"
                    )
                    self._aba_pagamentos.update(
                        intervalo, [linha_em_branco[COL_NOME - 1:]],
                        value_input_option=ValueInputOption.user_entered,
                    )
            except Exception as exc:
                raise PlanilhaError(f"Erro ao adicionar participante: {exc}") from exc

    def remover_participante(self, nome: str) -> None:
        participante = self.buscar_participante(nome)
        if not participante:
            raise PlanilhaError(f'"{nome}" não foi encontrado na planilha.')
        with self._lock:
            try:
                self._aba_pagamentos.delete_rows(participante["linha"])
            except Exception as exc:
                raise PlanilhaError(f"Erro ao remover participante: {exc}") from exc

    def renomear_participante(self, nome_atual: str, nome_novo: str) -> None:
        participante = self.buscar_participante(nome_atual)
        if not participante:
            raise PlanilhaError(f'"{nome_atual}" não foi encontrado na planilha.')
        with self._lock:
            try:
                self._aba_pagamentos.update_cell(participante["linha"], COL_NOME, nome_novo)
            except Exception as exc:
                raise PlanilhaError(f"Erro ao renomear participante: {exc}") from exc

    # ---------------------------------------------------------------- pagamentos / parcelas

    def registrar_pagamento(self, nome: str, valor: float) -> tuple[float, int]:
        """Grava o valor na próxima parcela vazia (C..N) do participante.

        Retorna (novo_total, número_da_parcela_preenchida). Não sobrescreve a coluna de
        total (O) se ela contiver fórmula — nesse caso o próprio Sheets recalcula.
        """
        participante = self.buscar_participante(nome)
        if not participante:
            raise PlanilhaError(f'"{nome}" não foi encontrado na planilha.')

        parcelas = participante["parcelas"]
        preenchidas = [v for v in parcelas if str(v).strip() != ""]
        numero_parcela = len(preenchidas) + 1
        if numero_parcela > NUM_PARCELAS:
            raise PlanilhaError(
                f"{participante['nome']} já quitou as {NUM_PARCELAS} parcelas. "
                "Não há parcela livre pra registrar esse pagamento."
            )

        coluna_destino = COL_PRIMEIRA_PARCELA + numero_parcela - 1
        linha = participante["linha"]

        with self._lock:
            try:
                self._aba_pagamentos.update_cell(linha, coluna_destino, valor)
            except Exception as exc:
                raise PlanilhaError(f"Erro ao registrar pagamento: {exc}") from exc

            try:
                celula_total = self._aba_pagamentos.cell(
                    linha, COL_TOTAL, value_render_option=ValueRenderOption.formula
                )
                eh_formula = isinstance(celula_total.value, str) and celula_total.value.startswith("=")
                if not eh_formula:
                    novo_total = sum(self._para_float(v) for v in parcelas) + valor
                    self._aba_pagamentos.update_cell(linha, COL_TOTAL, novo_total)
            except Exception as exc:
                raise PlanilhaError(f"Erro ao atualizar o total: {exc}") from exc

            try:
                total_atual = self._aba_pagamentos.cell(
                    linha, COL_TOTAL, value_render_option=ValueRenderOption.unformatted
                ).value
            except Exception as exc:
                raise PlanilhaError(f"Erro ao ler o total atualizado: {exc}") from exc

        return self._para_float(total_atual), numero_parcela

    @staticmethod
    def _para_float(valor) -> float:
        if valor in ("", None):
            return 0.0
        if isinstance(valor, (int, float)):
            return float(valor)
        texto = str(valor).replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(texto)
        except ValueError:
            return 0.0

    # ---------------------------------------------------------------- Config / Meta

    def obter_meta(self) -> float:
        try:
            registros = self._aba_config.get_all_records()
        except Exception as exc:
            raise PlanilhaError(f"Erro ao ler configurações: {exc}") from exc
        for linha in registros:
            if normalizar(str(linha.get("Chave", ""))) == "meta":
                return self._para_float(linha.get("Valor", 0))
        return 0.0

    def definir_meta(self, valor: float) -> None:
        with self._lock:
            try:
                registros = self._aba_config.get_all_records()
                for indice, linha in enumerate(registros, start=2):
                    if normalizar(str(linha.get("Chave", ""))) == "meta":
                        self._aba_config.update_cell(indice, 2, valor)
                        return
                self._aba_config.append_row(["meta", valor])
            except Exception as exc:
                raise PlanilhaError(f"Erro ao definir meta: {exc}") from exc

    def calcular_caixa(self) -> float:
        return sum(p["total"] for p in self.listar_participantes())
