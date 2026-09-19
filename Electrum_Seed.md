# 🔐 Electrum 2-of-3 Multisignature Wallet Guide

Electrum is a lightweight, non-custodial Bitcoin wallet. In a **2-of-3 multisignature wallet**, three cosigners participate, and any two can authorize a transaction.

## 🛠️ Create the Wallet

Each cosigner must use their own trusted device.

1. Open Electrum.
2. Select:

   ```text
   File → New/Restore → Multi-signature wallet
   ```

3. Choose **2 of 3**.
4. Select **Create a new seed**.
5. Write down the seed phrase and store it securely offline.
6. Set a strong wallet password.
7. Record the master public key (`xpub`) and share only the `xpub` with the other cosigners.

Repeat this process independently for cosigners A, B, and C.

> ⚠️ Never share seed phrases, private keys, or wallet passwords.

## 🔑 Configure the Cosigners

Each wallet contains its owner's seed and the other two cosigners' master public keys.

| Wallet | Local Seed | Imported Public Keys |
|---|---|---|
| A | A's seed | B's `xpub` and C's `xpub` |
| B | B's seed | A's `xpub` and C's `xpub` |
| C | C's seed | A's `xpub` and B's `xpub` |

All cosigners must use the same:

- **2-of-3** signing policy
- Wallet and script type
- Set of master public keys
- Derivation configuration, where applicable

After setup, compare several receiving addresses on all three devices. The addresses must match exactly before Bitcoin is deposited.

## 📥 Receive Bitcoin

1. Open the **Receive** tab.
2. Generate a receiving address.
3. Verify the complete address on all three wallets.
4. Send a small test amount first.
5. Confirm that the transaction appears correctly on every wallet.

## 📤 Send Bitcoin

### 1. Create and Sign

Cosigner A:

1. Creates the transaction.
2. Verifies the recipient address, amount, fee, and change outputs.
3. Adds the first signature.
4. Exports the partially signed transaction.

Depending on the Electrum version, this may be a PSBT or an Electrum transaction file.

### 2. Review and Cosign

Cosigner B:

1. Imports the partially signed transaction.
2. Independently verifies the recipient address, amount, fee, and change outputs.
3. Adds the second signature.

### 3. Broadcast

After the transaction has two valid signatures, any cosigner can broadcast it to the Bitcoin network.

Partially signed transactions can be transferred by:

- Transaction file
- QR code
- Removable media
- Authenticated communication channel

> 🔍 Always verify transaction details inside Electrum on a trusted device before signing.

## 💻 Electrum Console Seed Commands

Open the console from:

```text
View → Show Console
```

> ⚠️ The console is an advanced interface. Run only commands you understand and trust.

### Generate a Standard Electrum Seed

```python
make_seed(nbits=256, language="english", seed_type="standard")
```

### Generate a Native SegWit Electrum Seed

```python
make_seed(nbits=256, language="english", seed_type="segwit")
```

Native SegWit wallets normally use addresses beginning with `bc1`.

### Check an Electrum Seed Type

```python
from electrum.mnemonic import calc_seed_type

calc_seed_type("your seed words")
```

Typical results:

```text
'standard'
```

```text
'segwit'
```

Electrum seeds use Electrum's own seed-version system and must not automatically be treated as BIP39 mnemonics.

## 🛡️ Security Checklist

- Never share seed phrases, private keys, or wallet passwords.
- Never enter a real seed into a website, chat, email, cloud note, or untrusted application.
- Keep seed backups offline and in separate physical locations.
- Verify every `xpub` through an authenticated channel.
- Treat `xpub` values as private financial information: they cannot spend Bitcoin, but they can reveal addresses, balances, and transaction history.
- Verify addresses, amounts, fees, and change outputs before signing.
- Use trusted devices with disk encryption and current security updates.
- Test receiving, signing, recovery, and broadcasting with a small amount first.

## ♻️ Recovery Information

To reconstruct the wallet reliably, record:

- The **2-of-3** policy
- Wallet and script type
- All cosigner master public keys
- Derivation information
- Relevant Electrum version
- Instructions for locating the seed backups

Spending requires valid signing material from at least two cosigners. Test the recovery procedure before storing a significant balance.

1. Electrum
```
https://electrum.org
https://github.com/spesmilo/electrum
```
3. Wasabi Wallet
```
https://wasabiwallet.io
https://github.com/WalletWasabi/WalletWasabi
```
4. Sparrow Wallet
```
https://sparrowwallet.com
https://github.com/sparrowwallet/sparrow
```
