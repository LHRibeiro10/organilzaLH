# Bot da Caixinha 🎉

Bot de Telegram para controlar a caixinha de uma festa: cada participante paga
mensalmente até bater uma meta de valor total, e tudo é registrado numa
planilha do Google Sheets.

## Estrutura do projeto

```
main.py             # bot principal: handlers do Telegram e fluxo de confirmação
config.py           # carrega e valida as variáveis de ambiente
sheets_service.py   # toda a comunicação com o Google Sheets (gspread)
message_parser.py   # interpreta as mensagens em linguagem natural
access_control.py   # controle de quem pode executar ações restritas
utils.py            # normalização de texto, formatação de moeda, parsing de valor
requirements.txt
.env.example
```

---

## 1. Criar o bot no Telegram (@BotFather)

1. Abra o Telegram e procure por **@BotFather**.
2. Envie `/newbot`.
3. Escolha um nome de exibição (ex.: "Caixinha da Festa") e um *username*
   terminado em `bot` (ex.: `caixinha_festa_bot`).
4. O BotFather vai responder com um **token** parecido com
   `123456789:ABCDefGhIJKlmNoPQRstuVWXyz`. Guarde esse valor — ele vai para
   `TELEGRAM_BOT_TOKEN` no `.env`.
5. Adicione o bot ao grupo da festa (ou converse com ele no privado).

## 2. Descobrir seu user ID do Telegram

Você precisa do seu user ID para colocar na lista de organizadores
(`AUTHORIZED_USER_IDS`).

1. No Telegram, procure por **@userinfobot** (ou **@myidbot**) e envie qualquer
   mensagem.
2. Ele responde com seu `Id`, algo como `987654321`.
3. Repita para cada amigo que também vai ser organizador, e junte os IDs
   separados por vírgula.

## 3. A planilha (estrutura de parcelas já existente)

Este bot foi adaptado para funcionar com uma planilha **já existente**, que
usa uma estrutura de 12 parcelas em vez de um total simples. O layout
esperado da aba de pagamentos é:

- **Linhas 2 a 5**: cabeçalho mesclado (título da confraternização, "PARCELAS"
  etc.) — o bot ignora completamente essas linhas.
- **Linha 5**: cabeçalho das colunas (texto livre, não é lido pelo bot).
- **Coluna B**: nome do participante.
- **Colunas C até N**: as 12 parcelas (parcela 1 = C, parcela 2 = D, ...,
  parcela 12 = N).
- **Coluna O**: total do participante. Pode ser uma fórmula (ex.:
  `=SOMA(C6:N6)`) — o bot **nunca sobrescreve** uma célula que já seja
  fórmula; se não for fórmula, ele mesmo recalcula e grava o total.
- **Dados dos participantes**: começam na linha definida em `LINHA_INICIAL`
  (padrão `6`) e vão até a última linha com nome preenchido na coluna B —
  essa última linha é detectada dinamicamente, então adicionar/remover
  participantes não exige reconfiguração.
- **Linha "TOTAL"**: uma linha com `TOTAL` na coluna B, usada para o total
  geral. O bot identifica essa linha pelo texto e nunca a trata como
  participante; ao adicionar alguém novo, a nova linha é inserida **antes**
  dela (empurrando-a para baixo) e preservando a formatação da linha
  anterior.

Se o nome da aba ou a linha inicial forem diferentes na sua planilha, ajuste
`SHEET_ABA_PAGAMENTOS` e `LINHA_INICIAL` no `.env` — nada disso é fixo no
código.

### 3.1. Aba de configuração (meta)

O bot também usa uma aba chave-valor para guardar a meta:

```
Chave | Valor
meta  | 5500
```

Se a aba (nome definido em `SHEET_ABA_CONFIG`, padrão `Config`) ainda não
existir, **o bot cria ela automaticamente** na primeira execução, já com
`meta = META_PADRAO` (padrão `5500`). Você não precisa criá-la manualmente.

### 3.2. Pegar o ID da planilha

Copie o **ID da planilha**: é o trecho da URL entre `/d/` e `/edit`:
`https://docs.google.com/spreadsheets/d/SEU_ID_AQUI/edit`

### 3.3. Criar o projeto e a service account no Google Cloud

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) e crie
   um projeto novo (ou use um existente).
2. No menu **APIs e serviços > Biblioteca**, ative:
   - **Google Sheets API**
   - **Google Drive API**
3. Vá em **APIs e serviços > Credenciais > Criar credenciais > Conta de
   serviço**.
4. Dê um nome (ex.: `bot-caixinha`) e conclua a criação (não precisa de
   papéis especiais no projeto).
5. Na lista de contas de serviço, clique na que você criou, vá na aba
   **Chaves > Adicionar chave > Criar nova chave**, escolha **JSON** e baixe
   o arquivo.
6. Salve esse arquivo na raiz do projeto como `credentials.json` (ou outro
   nome/caminho — só ajustar `GOOGLE_CREDENTIALS_FILE` no `.env`).

   ⚠️ **Nunca** suba esse arquivo para um repositório público — ele já está
   no `.gitignore`.

### 3.4. Compartilhar a planilha com a service account

1. Abra o `credentials.json` e copie o valor do campo `"client_email"`
   (algo como `bot-caixinha@seu-projeto.iam.gserviceaccount.com`).
2. Na planilha, clique em **Compartilhar** e adicione esse e-mail com
   permissão de **Editor**.

Sem esse passo o bot recebe erro de permissão ao tentar ler/gravar.

## 4. Preencher o `.env`

Copie `.env.example` para `.env` e preencha:

```
TELEGRAM_BOT_TOKEN=123456789:ABCDefGhIJKlmNoPQRstuVWXyz
AUTHORIZED_USER_IDS=987654321,123123123
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_SHEET_ID=1AbCDeFGhIjKlMnOpQrStUvWxYz
SHEET_ABA_PAGAMENTOS=PARCELAS
LINHA_INICIAL=6
SHEET_ABA_CONFIG=Config
META_PADRAO=5500
VALOR_CONFIRMACAO=500
```

- Use `GOOGLE_SHEET_ID` (recomendado) **ou** `GOOGLE_SHEET_NAME` — não
  precisa preencher os dois.
- `SHEET_ABA_PAGAMENTOS` é o nome exato da aba que já existe na sua planilha
  com a estrutura de parcelas.
- `LINHA_INICIAL` é a primeira linha com dados de participante (ajuste se o
  cabeçalho da sua planilha ocupar mais ou menos linhas).
- `SHEET_ABA_CONFIG`/`META_PADRAO` só importam na primeira execução, caso a
  aba de configuração ainda não exista (o bot a cria automaticamente).
- `VALOR_CONFIRMACAO` é o valor a partir do qual o bot pede confirmação antes
  de gravar um pagamento (proteção contra erro de digitação).

## 5. Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
python main.py
```

Se tudo estiver certo, o terminal mostra `Bot iniciado, aguardando
mensagens (polling)...`. Vá no Telegram e mande `/start` para o bot.

## 6. Exemplos de uso

- `Fulano pagou 50` / `Fulano pagou 50 reais` / `Fulano pagou R$ 50,00`
  → grava o valor na **próxima parcela vazia** (1ª, 2ª, 3ª... até a 12ª) do
  Fulano. Se as 12 já estiverem preenchidas, o bot avisa que ele já quitou e
  não grava nada.
- `Fulano não pagou` / `Fulano nao pagou` → corrige um pagamento marcado por
  engano: remove a **última parcela preenchida** do Fulano (apaga o valor e a
  formatação verde/moeda daquela célula) e recalcula o total. Pede
  confirmação por botão antes de executar, e avisa se a pessoa não tiver
  nenhuma parcela paga.
- `Trocar nome Fulano para Fulano Silva`
- `Adicionar participante Beltrano`
- `Remover participante Beltrano`
- `Definir meta 5000`
- `Quem já pagou?` / `Quem ainda não pagou?`
- `Quanto Fulano pagou?` → soma das parcelas preenchidas (ou a coluna O)
- `Quanto tem em caixa?`
- `Quanto falta pra meta?`
- `/resumo` ou `Resumo`

As ações de registrar pagamento, **remover pagamento**, editar nome,
cadastrar/remover participante e definir meta só funcionam para quem está em
`AUTHORIZED_USER_IDS`; qualquer pessoa no chat pode fazer consultas.

## 7. Subir no Railway ou Render

O bot usa *polling* (não webhook), então a hospedagem só precisa manter o
processo `python main.py` rodando continuamente.

### Railway

1. Crie um projeto novo e conecte o repositório (ou use `railway up` via
   CLI a partir desta pasta).
2. Em **Variables**, cadastre todas as chaves do `.env` (`TELEGRAM_BOT_TOKEN`,
   `AUTHORIZED_USER_IDS`, `GOOGLE_SHEET_ID`, `VALOR_CONFIRMACAO`, etc.).
3. Para as credenciais do Google, **não** suba o `credentials.json` direto:
   crie uma variável `GOOGLE_CREDENTIALS_JSON` com o conteúdo do arquivo e
   adicione, no início do `sheets_service.py` (ou num pequeno script de
   inicialização), a gravação desse conteúdo em `credentials.json` antes do
   bot subir — ou ajuste `SheetsService` para ler as credenciais direto da
   variável de ambiente com `Credentials.from_service_account_info`.
4. Defina o **Start Command** como `python main.py`.

### Render

1. Crie um **Background Worker** (não "Web Service", já que não há
   webhook/porta HTTP).
2. Build command: `pip install -r requirements.txt`.
3. Start command: `python main.py`.
4. Cadastre as mesmas variáveis de ambiente em **Environment**, com a mesma
   observação sobre o `credentials.json` acima.

## 8. Tratamento de erros

- Planilha fora do ar / sem permissão → o bot responde com uma mensagem
  amigável (`📛 ...`) em vez de quebrar.
- Nome não encontrado → o bot avisa e, no caso de pagamento, oferece
  cadastrar o participante na hora.
- Valor inválido (texto que não é número) → o bot pede para reformular.
- Participante com as 12 parcelas já preenchidas → o bot avisa que já quitou
  e não registra um 13º pagamento.
- Pagamentos altos (acima de `VALOR_CONFIRMACAO`) exigem confirmação por
  botão antes de gravar.
- Remover pagamento (`Fulano não pagou`) é uma ação destrutiva: o bot sempre
  pede confirmação por botão (✅/❌) antes de apagar a parcela, mostrando qual
  parcela e valor serão removidos. Se a pessoa não tiver nenhuma parcela
  preenchida, o bot avisa e não faz nada.
- Possível duplicidade: como a planilha real não tem mais uma coluna de
  histórico com datas, o bot guarda em memória o último nome+valor
  registrado por chat; se o mesmo nome+valor for repetido dentro de 2
  minutos, ele pede confirmação antes de gravar de novo (proteção contra
  mensagem enviada duas vezes por engano). Esse controle é por processo —
  reinicia se o bot for reiniciado.
#   o r g a n i l z a L H  
 