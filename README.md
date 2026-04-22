# EyeAria

Vizuální nástroj pro stavbu AI a IoT datových toků (pipelines). Projekt využívá framework [NiceGUI](https://nicegui.io/) pro interaktivní uživatelské rozhraní, Docker pro snadné nasazení a plně podporuje hardwarovou akceleraci včetně AI čipů Hailo.

## Funkce a vlastnosti
- **Vizuální editor (Canvas):** Intuitivní drag & drop rozhraní s podporou přibližování (zoom), posouvání a s interaktivní minimapou.
- **Automatické načítání uzlů:** Systém dynamicky načítá potřebné moduly (uzly) ze zdrojových souborů, což usnadňuje rozšiřování aplikace o nové prvky (např. kamera, filtry, AI).
- **Předletová kontrola:** Před každým startem datového toku (Pipeliny) proběhne kontrola vygenerovaného schématu, aby se předešlo spuštění se špatnou konfigurací uzlů.
- **Export a Import:** Svou vytvořenou strukturu si můžete pohodlně stáhnout do formátu JSON a kdykoliv později znovu načíst, a to včetně přesných pozic uzlů na plátně.
- **Integrovaný Dashboard:** Díky Streamlitu je možné přidat i komplexní datovou analytiku.

---

## Nasazení a instalace (Deployment)

Pro nasazení se využívá nástroj Docker Compose, který se postará o vytvoření sítě, databáze i kontejneru aplikace. Kontejner `eyearia` vyžaduje speciální oprávnění pro přímou komunikaci s hardwarem vašeho zařízení (GPIO, I2C, Hailo).

### Požadavky
- Nainstalovaný Docker a Docker Compose.

### Spuštění
V kořenové složce projektu (tam kde se nachází soubor `docker-compose.yml`) spusťte:

```bash
docker-compose up -d --build
```

Tento příkaz spustí na pozadí 3 služby:
1. **postgres** - PostgreSQL databázi na portu `5432`.
2. **eyearia** - Hlavní řídící aplikaci s grafickým editorem dostupnou na portu `8082`.
3. **dashboard** - Streamlit dashboard pro analýzu dat na portu `8501`.

*Poznámka:* Hlavní služba běží v režimu `privileged: true` pro získání přístupu k `/dev/hailo0`, `/dev/gpiomem`, `/dev/i2c-1` a připojeným kamerám přes `/dev/video0`.

---

## Zjednodušená instalace Hailo (např. Raspberry Pi 5)

Pro efektivní běh AI modelů projekt nativně podporuje hardwarový akcelerátor Hailo. Níže naleznete rychlý postup instalace ovladačů.

1. **Aktualizace systému:**
   Ujistěte se, že používáte nejnovější verze balíčků.
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   ```

2. **Povolení rychlého PCIe (volitelné, ale doporučené):**
   Pro zajištění dostatečné propustnosti na Raspberry Pi 5 povolte PCIe Gen 3.
   ```bash
   sudo raspi-config
   ```
   *Jděte do `Advanced Options` -> `PCIe Speed` a zvolte `Gen 3`.*

3. **Instalace základních knihoven:**
   Nainstalujte kompletní balíček nástrojů Hailo.
   ```bash
   sudo apt install hailo-all
   ```

4. **Restart:**
   ```bash
   sudo reboot
   ```

Po restartu můžete ověřit funkčnost akcelerátoru například příkazem `hailortcli fw-control identify` nebo vyhledáním Hailo zprávy v jádře přes `dmesg | grep hailo`.

---

## Použití a Tutoriál

Jakmile je projekt nasazený přes Docker Compose, otevřete webový prohlížeč a přejděte na:
**`http://<IP_ADRESA_VAŠEHO_ZAŘÍZENÍ>:8082`**

### 1. Základy práce s plátnem
- Kliknutím a tažením po prázdné ploše (případně využíváním dotyku na mobilních zařízeních) se **posouváte** plátnem.
- Využijte tlačítka `+` a `-` v pravém dolním rohu nebo kolečko myši pro **přiblížení a oddálení** (zoom).
- Tlačítkem zaměřovače vpravo dole rychle **vycentrujete pohled**.
- Pro snazší navigaci u rozsáhlých projektů je v pravém horním rohu k dispozici živá **minimapa**.

### 2. Skládání Pipeliny
1. Tvorbu zahájíte stisknutím výrazného tlačítka **ADD SOURCE NODE** v centru plátna. Otevře se dialog pro výběr vstupního uzlu (Gateway, Kamera, apod.).
2. Další zpracovávací (Output) a řídící uzly přidáte přímo k existujícím uzlům přes kontextová tlačítka přímo na daném uzlu.
3. Uzly můžete po plátně jednoduše přesouvat, čáry a propojení se budou automaticky aktualizovat.
4. Nepotřebné uzly lze snadno smazat (s výjimkou základní Input Gateway).

### 3. Spuštění procesu
Jakmile máte všechny komponenty propojené, stiskněte nahoře v hlavní liště tlačítko **START PIPELINE**.
Před samotným startem systém zkompiluje logiku a zkontroluje propojení. Pokud projde "pre-flight check", zelené tlačítko se změní na červené a Pipelina začne zpracovávat data. Pro ukončení zpracování zvolte **STOP PIPELINE**.

### 4. Export a Import
Abyste nepřišli o svou práci, je v navigačním panelu zabudována funkce uložení.
- **Export (Ikona šipky dolů):** Vygeneruje `full_pipeline_config.json`, který obsahuje nastavení logiky i vizuální rozvržení prvků.
- **Import (Ikona šipky nahoru):** Otevře dialog pro bezpečné nahrání dříve vytvořeného konfiguračního souboru a okamžité obnovení plátna.

### 5. Bezpečnostní ukončení
V pravém horním rohu se nachází tlačítko **KILL**. Slouží jako bezprostřední pojistka pro kritické zastavení běhu celé aplikace (shutdown aplikaci i spojení).
```python

with open("README.md", "w", encoding="utf-8") as f:
    f.write(content)

print("Fetched content: README.md generated successfully.")

```