# Como Python encontra a biblioteca pypncp

## GitHub e PyPI têm papéis diferentes

O GitHub hospeda o repositório: código-fonte, histórico Git, Issues e Pull Requests.

O PyPI hospeda pacotes Python publicados para instalação. O nome publicado desta biblioteca é `pypncp`.

Normalmente, o computador do usuário não consulta o GitHub quando executa:

```python
from pypncp import PNCPClient
```

## Instalação normal pelo PyPI

Quando alguém executa:

```powershell
python -m pip install pypncp
```

o `pip` normalmente:

1. consulta o índice configurado, geralmente o PyPI;
2. escolhe uma distribuição compatível com a versão do Python e o sistema;
3. baixa o pacote e suas dependências;
4. instala tudo na pasta `site-packages` daquele ambiente Python;
5. grava metadados como nome e versão instalados.

Cada ambiente virtual possui seu próprio `site-packages`. Instalar em um ambiente não instala automaticamente nos demais.

## O que acontece no import

Ao executar:

```python
from pypncp import PNCPClient
```

o mecanismo de importação percorre os locais registrados em `sys.path`. Entre eles estão a pasta do programa, a biblioteca padrão e o `site-packages` do Python em execução.

Quando encontra o pacote `pypncp`, o Python carrega seu `__init__.py`. Esse arquivo expõe `PNCPClient`, que então pode ser importado pelo aplicativo.

É possível verificar o arquivo realmente carregado:

```powershell
python -c "import pypncp; print(pypncp.__file__)"
```

E consultar os metadados da instalação:

```powershell
python -m pip show pypncp
```

É importante usar `python -m pip` com o mesmo `python` que executará o aplicativo. Assim evitamos instalar a biblioteca em um Python e rodar o programa com outro.

## Instalação editável durante o desenvolvimento

No repositório original foi usado:

```powershell
python -m pip install -e ".[dev]"
```

O `-e` significa instalação editável. Em vez de copiar uma versão independente do código para uso normal, o ambiente registra uma ligação com o checkout local.

Por isso, alterações feitas nos arquivos de `src/pypncp` ficam disponíveis ao importar a biblioteca naquele ambiente, sem reinstalar a cada edição.

Essa modalidade é apropriada para contribuir com o `pypncp`, mas não para distribuir o aplicativo aos usuários finais.

## Instalação diretamente do GitHub

Também é tecnicamente possível instalar uma revisão Git específica:

```powershell
python -m pip install "pypncp @ git+https://github.com/gabrielgz0/pypncp.git@REVISAO"
```

Isso é útil para testar uma correção ainda não publicada no PyPI. Para versões normais do aplicativo, é preferível declarar uma versão publicada e reproduzível.

## Aplicativo empacotado

Quando o aplicativo desktop for empacotado, a ferramenta de distribuição reunirá o interpretador Python, o código do aplicativo, o `pypncp` e as demais dependências.

Nesse cenário, o usuário final não precisará:

- clonar o GitHub;
- instalar Python;
- executar `pip`;
- saber onde está o `site-packages`.

O carregador do aplicativo encontrará a cópia empacotada do `pypncp` dentro da própria distribuição.

## Resumo

```text
Desenvolvedor do pypncp:
GitHub -> clone -> pip install -e . -> import usa o checkout local

Desenvolvedor de outro sistema:
PyPI -> pip install pypncp -> import usa o site-packages

Usuário final do aplicativo desktop:
baixa o aplicativo empacotado -> dependências já estão incluídas
```
