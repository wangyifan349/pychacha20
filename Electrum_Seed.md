# 🔐 Electrum Console Seed Commands

## Open the Electrum Console
In Electrum, open:

```text
View → Show Console
```

The console lets you call Electrum's internal Python functions directly.

## 🟠 Generate a Standard Seed
```python
make_seed(nbits=256, language="english", seed_type="standard")
```
- `nbits=256` — entropy size used for seed generation.
- `language="english"` — generate English seed words.
- `seed_type="standard"` — generate an Electrum Standard seed.

## 🟢 Generate a Native SegWit Seed
```python
make_seed(nbits=256, language="english", seed_type="segwit")
```
- `nbits=256` — entropy size used for seed generation.
- `language="english"` — generate English seed words.
- `seed_type="segwit"` — generate an Electrum SegWit seed, normally used for native SegWit wallets with `bc1...` addresses.

## 🔎 Check the Seed Type
Import the seed-type detection function and check a seed:

```python
from electrum.mnemonic import calc_seed_type
calc_seed_type("your seed words")
```

Typical results:

```text
'standard'
```

or:

```text
'segwit'
```

## 📌 Command Summary
```python
# Generate Standard seed
make_seed(nbits=256, language="english", seed_type="standard")

# Generate SegWit seed
make_seed(nbits=256, language="english", seed_type="segwit")

# Import seed-type checker
from electrum.mnemonic import calc_seed_type

# Check seed type
calc_seed_type("your seed words")
```

## ⚠️ Security
Never paste a real wallet seed into websites, chat services, cloud notes, or untrusted software. Anyone who obtains the seed can control the wallet. Electrum seeds also use Electrum's own seed-version system and should not automatically be treated as standard BIP39 mnemonics.
