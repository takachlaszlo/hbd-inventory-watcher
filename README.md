# HBD Inventory Watcher

A `hbd_inventory_report.py` a HostingBy.Design dedikált szerveres kategóriaoldalait ellenőrzi, kiolvassa az összes listázott konfigurációt, készletszámot, havi árat és rendelési hivatkozást, majd részletes jelentést küld e-mailben.

Ez a leírás szándékosan **kezdőknek is követhető**, és végigvezet a teljes rendszeren:

1. a figyelő elkészíti a jelentést;
2. a helyi Postfix a levelet egy saját, szerveren tárolt postafiókba kézbesíti;
3. a Dovecot biztonságos IMAP-kapcsolaton elérhetővé teszi a postafiókot;
4. az iPhone Mail alkalmazása közvetlenül a saját szerverről tölti le a levelet.

Ehhez nem kell Gmail-jelszó, alkalmazásjelszó, Telegram, Brevo vagy más külső értesítési szolgáltatás.

> [!IMPORTANT]
> A README-ben szereplő `mail.example.com`, `SERVER_USER` és hasonló értékek **helyőrzők**. Ezeket mindig a saját szervered adataira kell cserélni.

---

## Tartalomjegyzék

- [Mit építünk fel?](#mit-építünk-fel)
- [Biztonsági tudnivalók](#biztonsági-tudnivalók)
- [Követelmények](#követelmények)
- [1. A figyelő telepítése](#1-a-figyelő-telepítése)
- [2. A levelezési rendszer előzetes ellenőrzése](#2-a-levelezési-rendszer-előzetes-ellenőrzése)
- [3. Postfix és Dovecot telepítése](#3-postfix-és-dovecot-telepítése)
- [4. Saját postafiók létrehozása](#4-saját-postafiók-létrehozása)
- [5. Maildir helyi kézbesítés beállítása](#5-maildir-helyi-kézbesítés-beállítása)
- [6. TLS-tanúsítvány kiválasztása](#6-tls-tanúsítvány-kiválasztása)
- [7. Dovecot IMAP és hitelesítés beállítása](#7-dovecot-imap-és-hitelesítés-beállítása)
- [8. Postfix SMTP submission beállítása](#8-postfix-smtp-submission-beállítása)
- [9. Tűzfal és portok](#9-tűzfal-és-portok)
- [10. A teljes levelezési rendszer tesztelése](#10-a-teljes-levelezési-rendszer-tesztelése)
- [11. iPhone Mail beállítása](#11-iphone-mail-beállítása)
- [12. A figyelő konfigurálása](#12-a-figyelő-konfigurálása)
- [13. Hatóránkénti futtatás cronból](#13-hatóránkénti-futtatás-cronból)
- [14. Tanúsítvány-megújítás](#14-tanúsítvány-megújítás)
- [15. Hibakeresés](#15-hibakeresés)
- [16. Biztonsági ellenőrzőlista](#16-biztonsági-ellenőrzőlista)

---

## Mit építünk fel?

A működés útvonala:

```text
HostingBy.Design weboldal
          │
          ▼
hbd_inventory_report.py
          │
          ▼
/usr/sbin/sendmail → Postfix
          │
          ▼
/home/hbdmail/Maildir
          │
          ▼
Dovecot IMAP, TLS, TCP 993
          │
          ▼
iPhone Mail
```

A 587-es SMTP submission port azért szükséges, mert az iPhone a kézzel hozzáadott IMAP-fiókhoz kimenő SMTP-kiszolgálót is kér és ellenőriz. A figyelő maga nem az 587-es porton küld: közvetlenül a helyi `sendmail` parancsnak adja át a levelet.

### Miért nem küldünk közvetlenül Gmail-címre?

Egy önálló szerverről Gmailbe küldött levélhez rendszerint megfelelő küldő domain, SPF vagy DKIM, helyes DNS és jó küldői reputáció szükséges. Ezek hiányában a Gmail például `550 5.7.26` hibával elutasíthatja a levelet.

Ebben a megoldásban a levél **nem hagyja el a szervert**. A telefon közvetlenül a szerveren lévő postafiókot olvassa, ezért nincs szükség külső levéltovábbításra.

---

## Biztonsági tudnivalók

A levelezési portok internetre nyitása után rövid időn belül automatikus szkennerek és bejelentkezési próbálkozások jelenhetnek meg a naplóban. Ez nem feltétlenül célzott támadás, de a biztonságos konfiguráció kötelező.

Minimumkövetelmények:

- a 993-as IMAP és 587-es SMTP porton kötelező TLS;
- hosszú, egyedi postafiók-jelszó;
- a 25-ös SMTP-port ne legyen nyilvánosan elérhető, ha csak helyi kézbesítésre van szükség;
- a privát TLS-kulcsot soha ne másold a GitHub-repóba;
- a valódi `hbd-inventory.ini` fájlt ne commitold;
- rendszeresen ellenőrizd a Dovecot és Postfix naplóit;
- Fail2ban használata erősen ajánlott.

A repó `.gitignore` fájlja kizárja a valódi INI-konfigurációt, naplókat és tipikus biztonsági mentéseket, de commit előtt mindig ellenőrizd:

```bash
git status
```

---

## Követelmények

A példák Debian 12 rendszert feltételeznek.

Szükséges:

- működő Debian vagy Ubuntu szerver;
- `sudo` jogosultság;
- Python 3.10 vagy újabb;
- Postfix;
- Dovecot IMAP;
- a szerverre mutató, tanúsítvánnyal rendelkező hosztnév, például `mail.example.com`;
- kívülről elérhető TCP 993 és 587 port;
- iPhone vagy más IMAP-kliens.

A Swizzin rendszerint már telepít nginxet és érvényes TLS-tanúsítványt. A leírás megmutatja, hogyan használható ugyanaz a tanúsítvány a Dovecothoz és a Postfixhez.

---

# 1. A figyelő telepítése

```bash
git clone https://github.com/takachlaszlo/hbd-inventory-watcher.git
cd hbd-inventory-watcher

sudo apt update
sudo apt install -y python3 python3-bs4

chmod 700 hbd_inventory_report.py
mkdir -p ~/.config ~/.local/state
cp hbd-inventory.example.ini ~/.config/hbd-inventory.ini
chmod 600 ~/.config/hbd-inventory.ini
```

A jelentés előnézete e-mail nélkül:

```bash
python3 hbd_inventory_report.py --print-only
```

Ezen a ponton a weboldal-feldolgozást már lehet tesztelni. Az e-mail-küldés csak a következő fejezetek után működik.

---

# 2. A levelezési rendszer előzetes ellenőrzése

## 2.1. A szerver neve

```bash
hostname
hostname -f
```

A `hostname -f` eredménye lehetőleg teljes domainnév legyen, például:

```text
mail.example.com
```

A kizárólag számokból álló név, például `123456`, problémát okozhat a Postfix helyi kézbesítőjének:

```text
fatal: unable to use my own hostname
```

Csak akkor módosítsd a gépnevet, ha a jelenlegi név hibás vagy nem teljes domainnév. Előbb készíts mentést:

```bash
sudo cp -a /etc/hostname /etc/hostname.bak
sudo cp -a /etc/hosts /etc/hosts.bak
```

Példa:

```bash
sudo hostnamectl set-hostname mail.example.com
```

Az `/etc/hosts` fájlban legyen ehhez hasonló sor:

```text
127.0.1.1   mail.example.com mail
```

Szerkesztés:

```bash
sudo nano /etc/hosts
```

Ellenőrzés:

```bash
hostname -f
getent hosts "$(hostname -f)"
```

> [!CAUTION]
> Meglévő Swizzin-szerveren ne cseréld le gondolkodás nélkül a már működő hosztnevet. A levelezéshez használt névnek elsősorban a TLS-tanúsítvánnyal kell egyeznie.

## 2.2. Melyik névre érvényes a Swizzin tanúsítványa?

```bash
sudo nginx -T 2>/dev/null \
  | grep -E 'server_name|ssl_certificate(_key)?'
```

Példakimenet:

```text
server_name mail.example.com;
ssl_certificate /etc/nginx/ssl/mail.example.com/fullchain.pem;
ssl_certificate_key /etc/nginx/ssl/mail.example.com/key.pem;
```

Jegyezd fel ezt a három adatot:

```text
MAIL_HOST = mail.example.com
CERT      = /etc/nginx/ssl/mail.example.com/fullchain.pem
KEY       = /etc/nginx/ssl/mail.example.com/key.pem
```

A telefonon később pontosan a `MAIL_HOST` értéket kell használni. Másik hosztnév esetén az iPhone tanúsítványhibát jelezhet.

## 2.3. DNS ellenőrzése

```bash
getent ahostsv4 mail.example.com
```

A kimenetnek a szerver nyilvános IPv4-címét kell tartalmaznia.

A szerver publikus IPv4-címe például így kérdezhető le:

```bash
ip -4 route get 1.1.1.1 | awk '{print $7; exit}'
```

---

# 3. Postfix és Dovecot telepítése

```bash
sudo apt update
sudo apt install -y postfix dovecot-core dovecot-imapd
```

A Postfix telepítője kérdéseket tehet fel.

Válaszd:

```text
Internet Site
```

A rendszerlevelezési névhez add meg a teljes szervernevet, például:

```text
mail.example.com
```

Ellenőrzés:

```bash
postconf mail_version
sudo dovecot --version
```

Szolgáltatások:

```bash
sudo systemctl enable --now postfix dovecot
sudo systemctl is-active postfix
sudo systemctl is-active dovecot
```

Mindkettőnél ezt kell látni:

```text
active
```

---

# 4. Saját postafiók létrehozása

A példában a postafiók rendszerfelhasználója `hbdmail`.

```bash
if ! id hbdmail >/dev/null 2>&1; then
    sudo adduser \
      --disabled-password \
      --gecos "" \
      --shell /usr/sbin/nologin \
      hbdmail
fi

sudo passwd hbdmail
```

Adj meg egy hosszú, egyedi jelszót. Ezt a jelszót kell majd az iPhone-on használni.

A jelszó ne szerepeljen:

- a README-ben;
- shell-parancsban;
- GitHubon;
- a figyelő INI-fájljában.

A felhasználó ellenőrzése:

```bash
getent passwd hbdmail
```

Példakimenet:

```text
hbdmail:x:1001:1001:,,,:/home/hbdmail:/usr/sbin/nologin
```

---

# 5. Maildir helyi kézbesítés beállítása

## 5.1. Maildir létrehozása

```bash
sudo install -d \
  -m 700 \
  -o hbdmail \
  -g hbdmail \
  /home/hbdmail/Maildir \
  /home/hbdmail/Maildir/cur \
  /home/hbdmail/Maildir/new \
  /home/hbdmail/Maildir/tmp
```

Ellenőrzés:

```bash
sudo ls -ld \
  /home/hbdmail \
  /home/hbdmail/Maildir \
  /home/hbdmail/Maildir/{cur,new,tmp}
```

## 5.2. Postfix helyi kézbesítése Maildirbe

```bash
sudo postconf -e 'home_mailbox = Maildir/'
sudo postconf -e 'mailbox_command ='
sudo postfix check
sudo systemctl restart postfix
```

Ellenőrzés:

```bash
postconf home_mailbox mailbox_command
```

A kívánt eredmény:

```text
home_mailbox = Maildir/
mailbox_command =
```

## 5.3. Helyi tesztlevél

```bash
{
    printf 'From: HBD Watch <hbdmail@localhost>\n'
    printf 'To: hbdmail\n'
    printf 'Subject: HBD helyi postafiok teszt\n'
    printf 'MIME-Version: 1.0\n'
    printf 'Content-Type: text/plain; charset=UTF-8\n'
    printf '\n'
    printf 'A helyi Maildir kezbesites mukodik.\n'
} | /usr/sbin/sendmail -i hbdmail

sleep 2

sudo find /home/hbdmail/Maildir/new \
  -maxdepth 1 \
  -type f \
  -printf '%TY-%Tm-%Td %TH:%TM %f\n'
```

Ha hosszú fájlnév jelenik meg, a helyi kézbesítés működik.

Ha nincs kimenet, nézd meg:

```bash
sudo postqueue -p
sudo tail -n 80 /var/log/mail.log
```

Ha nincs `/var/log/mail.log`:

```bash
sudo journalctl --since '-10 minutes' --no-pager \
  | grep -Ei 'postfix|dovecot|status=|dsn=|reject'
```

Sikeres helyi kézbesítés:

```text
status=sent (delivered to maildir)
```

---

# 6. TLS-tanúsítvány kiválasztása

A következő példákban:

```bash
MAIL_HOST='mail.example.com'
CERT='/etc/nginx/ssl/mail.example.com/fullchain.pem'
KEY='/etc/nginx/ssl/mail.example.com/key.pem'
```

A saját értékeidet használd.

## 6.1. Fájlok ellenőrzése

```bash
sudo test -r "$CERT" && echo 'A tanúsítvány olvasható.'
sudo test -r "$KEY" && echo 'A privát kulcs olvasható.'
```

## 6.2. A tanúsítvány neveinek ellenőrzése

```bash
sudo openssl x509 \
  -in "$CERT" \
  -noout \
  -subject \
  -issuer \
  -dates \
  -ext subjectAltName
```

A `subjectAltName` részben szerepelnie kell:

```text
DNS:mail.example.com
```

A telefonon csak olyan hosztnevet használj, amely szerepel a tanúsítványban.

---

# 7. Dovecot IMAP és hitelesítés beállítása

Hozz létre külön konfigurációs fájlt. Így nem kell a disztribúció alapfájljait nagy mértékben átírni.

```bash
sudo nano /etc/dovecot/conf.d/99-hbd-mail.conf
```

Tartalma:

```conf
protocols = imap

mail_location = maildir:~/Maildir

disable_plaintext_auth = yes
auth_mechanisms = plain login

ssl = required
ssl_cert = </etc/nginx/ssl/mail.example.com/fullchain.pem
ssl_key = </etc/nginx/ssl/mail.example.com/key.pem

service imap-login {
  inet_listener imap {
    port = 0
  }

  inet_listener imaps {
    port = 993
    ssl = yes
  }
}

service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0660
    user = postfix
    group = postfix
  }
}
```

Cseréld ki a tanúsítvány és kulcs útvonalát a sajátodra.

A `<` jel a Dovecot konfigurációjában szándékos: azt jelenti, hogy a program a fájl tartalmát olvassa be.

## 7.1. Konfiguráció ellenőrzése

```bash
sudo doveconf -n
```

Ha nincs hiba:

```bash
sudo systemctl restart dovecot
sudo systemctl is-active dovecot
```

A 993-as port ellenőrzése:

```bash
sudo ss -ltnp | grep ':993'
```

A kiszolgált tanúsítvány ellenőrzése:

```bash
MAIL_HOST='mail.example.com'

timeout 10 openssl s_client \
  -connect 127.0.0.1:993 \
  -servername "$MAIL_HOST" \
  </dev/null 2>/dev/null \
  | openssl x509 \
      -noout \
      -subject \
      -issuer \
      -dates \
      -ext subjectAltName
```

## 7.2. Jelszó ellenőrzése

```bash
sudo doveadm auth test hbdmail
```

A parancs bekéri a jelszót.

Sikeres eredmény:

```text
passdb: hbdmail auth succeeded
```

---

# 8. Postfix SMTP submission beállítása

Az iPhone a kimenő SMTP-kiszolgálót is ellenőrzi. A 587-es porton:

- kötelező TLS;
- kötelező felhasználónév és jelszó;
- a Dovecot végzi a hitelesítést.

## 8.1. Dovecot SASL-támogatás ellenőrzése

```bash
postconf -a | grep -x dovecot
```

A kívánt kimenet:

```text
dovecot
```

## 8.2. Postfix főbeállítások

```bash
MAIL_HOST='mail.example.com'
CERT='/etc/nginx/ssl/mail.example.com/fullchain.pem'
KEY='/etc/nginx/ssl/mail.example.com/key.pem'

sudo postconf -e 'inet_interfaces = all'
sudo postconf -e "myhostname = $MAIL_HOST"
sudo postconf -e 'myorigin = $myhostname'
sudo postconf -e 'mydestination = $myhostname, localhost.$mydomain, localhost'
sudo postconf -e 'mynetworks = 127.0.0.0/8'
sudo postconf -e 'relayhost ='
sudo postconf -e 'inet_protocols = ipv4'

sudo postconf -e "smtpd_tls_cert_file = $CERT"
sudo postconf -e "smtpd_tls_key_file = $KEY"
sudo postconf -e 'smtpd_tls_security_level = may'

sudo postconf -e 'smtpd_sasl_type = dovecot'
sudo postconf -e 'smtpd_sasl_path = private/auth'
sudo postconf -e 'smtpd_sasl_auth_enable = no'
sudo postconf -e 'smtpd_sasl_security_options = noanonymous'
sudo postconf -e \
  'smtpd_relay_restrictions = permit_mynetworks,reject_unauth_destination'
```

A globális `smtpd_sasl_auth_enable = no` szándékos. A hitelesítést csak a külön 587-es submission szolgáltatásnál engedélyezzük.

## 8.3. A 25-ös port korlátozása és a 587-es port engedélyezése

Előbb készíts mentést:

```bash
sudo cp -a /etc/postfix/master.cf \
  "/etc/postfix/master.cf.bak-$(date +%Y%m%d-%H%M%S)"
```

Nyisd meg:

```bash
sudo nano /etc/postfix/master.cf
```

Keresd meg az aktív, nem `#` jellel kezdődő `smtp` és `submission` sorokat. A nyilvános alapértelmezett SMTP-sor például ilyen lehet:

```conf
smtp      inet  n       -       y       -       -       smtpd
```

Tegyél elé `#` jelet:

```conf
# smtp      inet  n       -       y       -       -       smtpd
```

Egy már aktív `submission` blokkot is kommentelj ki, hogy ne legyen két példány.

Ezután a fájl végére add hozzá:

```conf
# BEGIN HBD MAIL

# A 25-ös SMTP-port csak a saját szerveren érhető el.
127.0.0.1:smtp inet n - n - - smtpd

# Titkosított és hitelesített kliens-submission.
submission inet n - n - - smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_tls_auth_only=yes
  -o smtpd_tls_mandatory_protocols=>=TLSv1.2
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_sasl_type=dovecot
  -o smtpd_sasl_path=private/auth
  -o smtpd_sasl_security_options=noanonymous
  -o smtpd_sasl_tls_security_options=noanonymous
  -o smtpd_relay_restrictions=permit_sasl_authenticated,reject
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject

# END HBD MAIL
```

Mentés Nano-ban:

```text
Ctrl+O
Enter
Ctrl+X
```

Ellenőrzés és újraindítás:

```bash
sudo postfix check
sudo systemctl restart dovecot postfix
sudo systemctl is-active dovecot postfix
```

A Dovecot auth socket ellenőrzése:

```bash
sudo test -S /var/spool/postfix/private/auth \
  && echo 'A Dovecot auth socket létezik.'
```

Portok:

```bash
sudo ss -ltnp | grep -E ':(25|587|993)\b'
```

A kívánt felépítés:

- `127.0.0.1:25` — csak helyi Postfix-átadás;
- `0.0.0.0:587` — iPhone SMTP submission;
- `0.0.0.0:993` — iPhone IMAP.

A 25-ös port ne jelenjen meg `0.0.0.0:25` formában, ha nincs szükséged nyilvános levelezőszerverre.

---

# 9. Tűzfal és portok

Ha UFW aktív:

```bash
sudo ufw status
```

Nyisd meg a szükséges portokat:

```bash
sudo ufw allow 993/tcp
sudo ufw allow 587/tcp
sudo ufw reload
```

Ellenőrzés:

```bash
sudo ufw status numbered
```

Ha a szolgáltató külön hálózati tűzfalat használ, ott is engedélyezni kell:

```text
TCP 993
TCP 587
```

A 25-ös bejövő portot ehhez a megoldáshoz nem kell megnyitni.

---

# 10. A teljes levelezési rendszer tesztelése

## 10.1. IMAP TLS

```bash
MAIL_HOST='mail.example.com'

openssl s_client \
  -connect "$MAIL_HOST:993" \
  -servername "$MAIL_HOST" \
  </dev/null
```

A kimenet végén az ellenőrzési kód ideális esetben:

```text
Verify return code: 0 (ok)
```

## 10.2. SMTP STARTTLS tanúsítvány

```bash
MAIL_HOST='mail.example.com'

timeout 10 openssl s_client \
  -starttls smtp \
  -connect "$MAIL_HOST:587" \
  -servername "$MAIL_HOST" \
  </dev/null 2>/dev/null \
  | openssl x509 \
      -noout \
      -subject \
      -issuer \
      -dates \
      -ext subjectAltName
```

## 10.3. SMTP-felhasználónév és jelszó

Ez a teszt csak bejelentkezik, levelet nem küld.

```bash
read -rsp 'hbdmail jelszó: ' SMTP_PASS
echo
export SMTP_PASS

python3 - <<'PY'
import os
import smtplib
import ssl

host = "mail.example.com"
username = "hbdmail"
password = os.environ["SMTP_PASS"]

context = ssl.create_default_context()

with smtplib.SMTP(host, 587, timeout=20) as smtp:
    smtp.ehlo()
    smtp.starttls(context=context)
    smtp.ehlo()
    smtp.login(username, password)

print("RENDBEN: az SMTP TLS és hitelesítés sikeres.")
PY

unset SMTP_PASS
```

A Python-részben cseréld ki a `mail.example.com` értéket.

## 10.4. Valódi helyi levél

```bash
{
    printf 'From: HBD Inventory <hbdmail@mail.example.com>\n'
    printf 'To: hbdmail\n'
    printf 'Subject: HBD teljes teszt\n'
    printf 'MIME-Version: 1.0\n'
    printf 'Content-Type: text/plain; charset=UTF-8\n'
    printf '\n'
    printf 'A Postfix, Maildir es Dovecot rendszer mukodik.\n'
} | /usr/sbin/sendmail -i hbdmail
```

Ellenőrzés:

```bash
sleep 2
sudo find /home/hbdmail/Maildir/new \
  -maxdepth 1 \
  -type f \
  -printf '%TY-%Tm-%Td %TH:%TM %f\n'
```

---

# 11. iPhone Mail beállítása

Az iOS menüpontok verziótól függően kissé eltérhetnek.

Általános útvonal:

```text
Beállítások
→ Appok
→ Mail
→ Mail-fiókok
→ Fiók hozzáadása
→ Másik fiók hozzáadása
→ Mail-fiók
```

## 11.1. Alapadatok

```text
Név: HBD Inventory
E-mail: hbdmail@mail.example.com
Jelszó: a hbdmail rendszerfelhasználó jelszava
Leírás: HBD készletfigyelő
```

Válaszd az **IMAP** típust.

## 11.2. Bejövő levelezőszerver

```text
Hosztnév: mail.example.com
Felhasználónév: hbdmail
Jelszó: a hbdmail jelszava
SSL használata: bekapcsolva
Szerverport: 993
```

## 11.3. Kimenő levelezőszerver

```text
Hosztnév: mail.example.com
Felhasználónév: hbdmail
Jelszó: a hbdmail jelszava
SSL használata: bekapcsolva
Hitelesítés: Jelszó
Szerverport: 587
```

A 587-es port STARTTLS-t használ. Az iPhone felületén ezt rendszerint egyszerűen az **SSL használata** kapcsoló jelöli.

## 11.4. Ha az iPhone azt kérdezi: „Megpróbálja SSL nélkül?”

Válaszd:

```text
Nem
```

SSL nélkül ne folytasd. Ez általában az alábbiakat jelenti:

- a megadott hosztnév nem szerepel a tanúsítványban;
- a Dovecot még az alapértelmezett saját aláírású tanúsítványt használja;
- a 993-as port nem érhető el;
- a 587-es port vagy a STARTTLS nincs jól beállítva.

## 11.5. Új levelek lekérése

Egy saját IMAP-fiók nem feltétlenül támogat Apple Push kézbesítést. Az iPhone Mail beállításaiban válassz rendszeres lekérést, például 15 percet, ha ez az opció elérhető.

Általános útvonal:

```text
Beállítások
→ Appok
→ Mail
→ Mail-fiókok
→ Új adatok begyűjtése
```

---

# 12. A figyelő konfigurálása

Nyisd meg:

```bash
nano ~/.config/hbd-inventory.ini
```

Példa:

```ini
[email]
from = HBD Inventory <hbdmail@mail.example.com>
to = hbdmail

[report]
timezone = Europe/Budapest
request_delay_seconds = 3

[category_canada_1gbit]
name = Kanada – 1 Gbit
url = https://my.hostingby.design/index.php?rp=/store/leaseweb-canada

[category_netherlands_1gbit]
name = Hollandia – 1 Gbit
url = https://my.hostingby.design/index.php?rp=/store/lsw-1gbit

[category_netherlands_10gbit]
name = Hollandia – 10 Gbit
url = https://my.hostingby.design/index.php?rp=/store/lsw-10gbit
```

Védd le:

```bash
chmod 600 ~/.config/hbd-inventory.ini
```

Fontos:

```ini
to = hbdmail
```

Ez helyi címzett. A Postfix közvetlenül a `/home/hbdmail/Maildir` postafiókba kézbesít.

## 12.1. Előnézet

A repó könyvtárában:

```bash
python3 hbd_inventory_report.py --print-only
```

## 12.2. Valódi jelentés küldése

```bash
python3 hbd_inventory_report.py
```

Várt kimenet:

```text
A készletjelentés átadva a helyi Postfixnek.
```

Postafiók ellenőrzése:

```bash
sudo find /home/hbdmail/Maildir/new \
  -maxdepth 1 \
  -type f \
  -printf '%TY-%Tm-%Td %TH:%TM %f\n'
```

---

# 13. Hatóránkénti futtatás cronból

Előbb kérdezd le a pontos abszolút útvonalat:

```bash
pwd
```

Például:

```text
/home/SERVER_USER/hbd-inventory-watcher
```

Nyisd meg a felhasználói crontabot:

```bash
crontab -e
```

Add hozzá:

```cron
23 */6 * * * /usr/bin/flock -n /tmp/hbd-inventory-report.lock /usr/bin/timeout 180s /usr/bin/python3 /home/SERVER_USER/hbd-inventory-watcher/hbd_inventory_report.py >> /home/SERVER_USER/.local/state/hbd-inventory-report.log 2>&1
```

Cseréld ki a `SERVER_USER` értéket.

Ez a szerver időzónájában fut:

```text
00:23
06:23
12:23
18:23
```

Ellenőrzés:

```bash
crontab -l
```

Napló:

```bash
tail -n 100 ~/.local/state/hbd-inventory-report.log
```

Kézi teszt ugyanazzal a zárolással:

```bash
/usr/bin/flock -n /tmp/hbd-inventory-report.lock \
  /usr/bin/timeout 180s \
  /usr/bin/python3 \
  /home/SERVER_USER/hbd-inventory-watcher/hbd_inventory_report.py
```

---

# 14. Tanúsítvány-megújítás

A Swizzin vagy az nginx tanúsítványa időnként megújul. A Dovecot és Postfix folyamatot ezután újra kell tölteni, hogy az új tanúsítványt használja.

Kézi újratöltés:

```bash
sudo systemctl reload dovecot postfix
```

Ellenőrizd újra mindkét portot:

```bash
MAIL_HOST='mail.example.com'

openssl s_client \
  -connect "$MAIL_HOST:993" \
  -servername "$MAIL_HOST" \
  </dev/null 2>/dev/null \
  | openssl x509 -noout -dates -issuer -subject

openssl s_client \
  -starttls smtp \
  -connect "$MAIL_HOST:587" \
  -servername "$MAIL_HOST" \
  </dev/null 2>/dev/null \
  | openssl x509 -noout -dates -issuer -subject
```

Egyszerű, szolgáltatófüggetlen megoldásként napi egyszer újratölthetők a levelezési szolgáltatások:

```bash
sudo crontab -e
```

Példa:

```cron
17 4 * * * /usr/bin/systemctl reload dovecot postfix >/dev/null 2>&1
```

Ez nem újítja meg a tanúsítványt; csak biztosítja, hogy a szolgáltatások az nginx/Swizzin által már megújított fájlt újra beolvassák.

---

# 15. Hibakeresés

## 15.1. Gyors állapotfelmérés

```bash
echo '=== SZOLGÁLTATÁSOK ==='
sudo systemctl is-active postfix dovecot ssh

echo
echo '=== PORTOK ==='
sudo ss -ltnp | grep -E ':(25|587|993)\b' || true

echo
echo '=== POSTFIX VÁRÓLISTA ==='
sudo postqueue -p

echo
echo '=== POSTFIX BEÁLLÍTÁS ==='
postconf myhostname mydestination home_mailbox mailbox_command \
  smtpd_tls_cert_file smtpd_tls_key_file \
  smtpd_sasl_type smtpd_sasl_path

echo
echo '=== DOVECOT LÉNYEGES BEÁLLÍTÁSOK ==='
sudo doveconf -n \
  | grep -E '^(protocols|mail_location|ssl|ssl_cert|auth_mechanisms)'

echo
echo '=== LEGUTÓBBI NAPLÓ ==='
if sudo test -f /var/log/mail.log; then
    sudo tail -n 100 /var/log/mail.log
else
    sudo journalctl --since '-20 minutes' --no-pager \
      | grep -Ei 'postfix|dovecot'
fi
```

## 15.2. A Maildir üres

Ellenőrizd a várólistát:

```bash
sudo postqueue -p
```

Nézd meg a naplót:

```bash
sudo tail -n 100 /var/log/mail.log
```

A sikeres helyi kézbesítés sora:

```text
status=sent (delivered to maildir)
```

## 15.3. `fatal: unable to use my own hostname`

Ok: a rendszer gépneve valószínűleg kizárólag számokból áll vagy nem érvényes hosztnév.

```bash
hostname
hostname -f
```

Állíts be érvényes teljes nevet a [2.1. fejezet](#21-a-szerver-neve) szerint.

## 15.4. `/var/spool/postfix/etc/hosts and /etc/hosts differ`

Ha a Postfix ezt írja:

```text
warning: /var/spool/postfix/etc/hosts and /etc/hosts differ
```

Frissítsd a chrootolt másolatot:

```bash
sudo install -m 644 -o root -g root \
  /etc/hosts \
  /var/spool/postfix/etc/hosts

sudo postfix check
sudo systemctl restart postfix
```

## 15.5. Az iPhone nem tud SSL-lel kapcsolódni

Ellenőrizd:

```bash
MAIL_HOST='mail.example.com'

openssl s_client \
  -connect "$MAIL_HOST:993" \
  -servername "$MAIL_HOST" \
  </dev/null
```

Gyakori okok:

- hibás hosztnév a telefonon;
- a tanúsítvány nem erre a névre érvényes;
- Dovecot még a saját aláírású `/etc/dovecot/private/dovecot.pem` fájlt használja;
- a 993-as port blokkolt;
- a DNS másik IP-címre mutat.

## 15.6. Az SMTP-jelszót elutasítja

```bash
sudo doveadm auth test hbdmail
```

Szükség esetén állíts új jelszót:

```bash
sudo passwd hbdmail
```

Ellenőrizd a socketet:

```bash
sudo ls -l /var/spool/postfix/private/auth
```

Ellenőrizd a Dovecot SASL-t:

```bash
postconf -a | grep -x dovecot
```

## 15.7. A 587-es port nem figyel

```bash
sudo postfix check
sudo systemctl restart postfix
sudo ss -ltnp | grep ':587'
```

Nézd meg, hogy a `/etc/postfix/master.cf` fájlban az aktív `submission` sor nincs-e véletlenül kommentelve.

## 15.8. Sok idegen IP-cím jelenik meg a Dovecot naplójában

Nyilvános 993-as vagy 587-es portnál ez gyakori. Automatikus szkennerek próbálnak különböző protokollokat és titkosítási módokat.

Példák:

```text
unsupported protocol
no shared cipher
bad key share
no auth attempts
```

Ezek önmagukban nem jelentik azt, hogy valaki belépett. Sikeres vagy sikertelen hitelesítéseket külön keress:

```bash
sudo journalctl -u dovecot --since '-1 day' --no-pager \
  | grep -Ei 'auth|login|failed|succeeded'
```

## 15.9. Gmail `550 5.7.26` hibát ad

Ez nem a helyi Maildir hibája. A Gmail azért utasítja el a külső levelet, mert a küldő nincs megfelelően SPF-fel vagy DKIM-mel hitelesítve.

A jelen projekt ajánlott működése:

```ini
to = hbdmail
```

Ne Gmail-címet adj meg, hanem a saját helyi postafiókot, amelyet az iPhone IMAP-on olvas.

## 15.10. A `find` ezt írja: `Failed to restore initial working directory`

Ez akkor fordulhat elő, ha másik felhasználóként indított `find` nem fér hozzá az eredeti munkakönyvtárhoz.

Használd egyszerűen rootként:

```bash
sudo find /home/hbdmail/Maildir/new \
  -maxdepth 1 \
  -type f \
  -printf '%TY-%Tm-%Td %TH:%TM %f\n'
```

---

# 16. Biztonsági ellenőrzőlista

Telepítés után ellenőrizd:

- [ ] A `hbdmail` jelszava hosszú és egyedi.
- [ ] A 993-as port csak TLS-sel fogad kapcsolatot.
- [ ] Az 587-es port csak STARTTLS után enged hitelesítést.
- [ ] A 25-ös port csak `127.0.0.1` címen figyel.
- [ ] A Dovecot és Postfix ugyanazt az érvényes tanúsítványt használja.
- [ ] A telefonon használt hosztnév szerepel a tanúsítvány `subjectAltName` mezőjében.
- [ ] A privát kulcs nem került GitHubra.
- [ ] A valódi `~/.config/hbd-inventory.ini` nem került GitHubra.
- [ ] A cron naplója rendszeresen frissül.
- [ ] A Fail2ban aktív vagy más brute-force védelem működik.
- [ ] A rendszer biztonsági frissítései telepítve vannak.

Szolgáltatások gyors ellenőrzése:

```bash
sudo systemctl is-active postfix dovecot fail2ban
```

Frissítések:

```bash
sudo apt update
sudo apt upgrade
```

---

## Alternatív konfigurációs útvonal

A figyelő alapértelmezésben ezt olvassa:

```text
~/.config/hbd-inventory.ini
```

Másik fájl parancssorból:

```bash
python3 hbd_inventory_report.py \
  --config /path/to/config.ini
```

Vagy környezeti változóval:

```bash
HBD_INVENTORY_CONFIG=/path/to/config.ini \
  python3 hbd_inventory_report.py
```

---

## Függőségek

Debian/Ubuntu csomagból:

```bash
sudo apt install -y python3-bs4
```

Vagy `pip` használatával:

```bash
python3 -m pip install -r requirements.txt
```

---

## Fontos megjegyzés

A figyelő a HostingBy.Design nyilvános áruházi HTML-oldalait dolgozza fel. Az áruház későbbi átalakítása miatt szükség lehet a HTML-feldolgozó frissítésére. Feldolgozási hiba esetén a program nem jelenti tévesen azt, hogy nincs készlet, hanem külön ellenőrzési hibát ír a jelentésbe.

A projekt nem áll kapcsolatban a HostingBy.Design szolgáltatóval.

---

## Hivatalos háttérdokumentáció

- Dovecot: Postfix és Dovecot SASL
  - https://doc.dovecot.org/2.3/configuration_manual/howto/postfix_and_dovecot_sasl/
- Postfix TLS dokumentáció
  - https://www.postfix.org/TLS_README.html
- Apple: e-mail-fiók kézi hozzáadása iPhone-on
  - https://support.apple.com/102619
