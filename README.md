# ADNY Separador

Separador de canais para simulado serigráfico.

Aplicativo 100% gratuito para Windows de 64 bits. O objetivo é agilizar a separação de canais para estampa, usando um grupo padronizado de cores como ponto de partida para diferentes artes.

**Projeto em desenvolvimento inicial.** O resultado fica bastante adiantado, mas precisa de revisão manual no Photoshop. O aplicativo ainda necessita de melhorias.

## Qual versão escolher?

- **Clean:** motor principal de separação com interface enxuta e opções para salvar e exportar o resultado.
- **Completa:** mesmo motor com ferramentas e menus adicionais. Algumas ferramentas podem apresentar mau funcionamento ou não funcionar; nem todas as opções da interface estão concluídas.

As duas versões são gratuitas e exigem revisão do PSD antes da impressão.

## Como usar

1. Baixe o pacote ZIP da versão escolhida e extraia todo o conteúdo.
2. Na Completa, abra ADNY Separador.exe. Na Clean, abra ADNY Separador Clean.exe.
3. Mantenha a pasta _internal junto ao executável. Não mova apenas o EXE.
4. Use Arquivo → Abrir para carregar sua arte.
5. Aguarde a separação e compare a imagem original com a gerada. Confira os canais.
6. Use Salvar para exportar o resultado em PSD.
7. Abra o PSD no Photoshop e faça a revisão descrita abaixo.

Os pacotes de download incluem Python e as bibliotecas necessárias. Não é preciso instalar Python para usar os executáveis.

## Revisão no Photoshop

- Confira cada canal e o resultado combinado.
- Ajuste níveis, intensidade e saturação conforme a necessidade da arte.
- Exclua os canais desnecessários quando isso fizer sentido para o trabalho.
- Avalie especialmente a Base e o Branco Brilho: pode ser necessário reduzir a intensidade desses canais.
- Faça a reticulação e adicione as marcas de registro antes de imprimir os filmes.
- Verifique a saída conforme o seu processo serigráfico. Não existe uma configuração única para todas as artes.

### Aplicar imagem com Divisão

Quando necessário, para enfraquecer um canal:

1. Selecione o canal que deseja ajustar.
2. Abra Imagem → Aplicar imagem.
3. Confira o documento de origem e o canal usado na operação.
4. Em Mesclagem, escolha Divisão.
5. Observe a visualização e ajuste a intensidade conforme o resultado necessário.

A Base e o Branco Brilho costumam exigir essa avaliação. A operação é opcional e depende da arte. Os prints disponíveis no site mostram o canal Base como exemplo; não são uma configuração universal.

**O PSD exportado é uma etapa da preparação. Revise, reticule e adicione as marcas de registro no Photoshop antes da impressão.**

## Executar o código-fonte

Para desenvolvimento, instale Python 3.11 ou superior. Na raiz do projeto, execute preparar_ambiente.bat para criar o ambiente e instalar as dependências. Depois, use abrir_adny_separador.bat ou abrir_adny_separador_clean.bat.

O código fica nas pastas ADNY Separador e ADNY Separador Clean, com componentes compartilhados em apps e packages. Os executáveis ficam em dist.

## Site

O site está na pasta docs e pode ser visualizado com um servidor estático. Na raiz do projeto:

    python -m http.server 8765 --directory docs --bind 127.0.0.1

Abra http://127.0.0.1:8765 no navegador. A publicação do site usa GitHub Actions e os arquivos da pasta docs.

Os executáveis das duas versões são publicados nas [Releases](https://github.com/adnyestampa-dot/ADNY-Separador-de-canais/releases/latest). O código-fonte e o site ficam neste repositório; os pacotes completos de dist ficam nos downloads da release. O fluxo de publicação reconstrói e verifica as duas versões antes de publicar o site.

## Outro projeto ADNY

O [ADNY DTF Halftone](https://adnyestampa-dot.github.io/ADNY-DTF-Halftone/) é voltado à preparação de retícula para DTF têxtil. O ADNY Separador tem foco em separação de canais para simulado serigráfico.

## Links

- [Site](https://adnyestampa-dot.github.io/ADNY-Separador-de-canais/)
- [Downloads das duas versões](https://github.com/adnyestampa-dot/ADNY-Separador-de-canais/releases/latest)
