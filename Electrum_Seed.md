# 🔐 Electrum 2-of-3 Multisignature Wallet Guide

Electrum is a lightweight, non-custodial Bitcoin wallet. In a **2-of-3 multisignature wallet**, three cosigners participate, and any two can authorize a transaction.

## 🛠️ Create and Configure the Wallet

Each cosigner must complete the following steps independently on their own trusted device:

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

Configure each wallet as follows:

| Wallet | Local Seed | Imported Master Public Keys |
|---|---|---|
| A | A's seed | B's `xpub` and C's `xpub` |
| B | B's seed | A's `xpub` and C's `xpub` |
| C | C's seed | A's `xpub` and B's `xpub` |

All cosigners must use the same **2-of-3 policy**, wallet type, script type, cosigner public keys, and derivation configuration.

> ⚠️ Never share seed phrases, private keys, or wallet passwords.

## 📥 Verify Receiving Addresses

After setup, compare several receiving addresses on all three devices. They must match exactly before Bitcoin is deposited.

To print all receiving addresses, open:

```text
View → Show Console
```

Then run:

```python
print("\n".join(wallet.get_receiving_addresses()))
```

Each cosigner should run the command independently and compare the output.

> 🔍 Address differences indicate that the wallets were not configured identically. Do not deposit Bitcoin until the issue is resolved.

Before depositing a significant amount:

1. Verify a complete receiving address on every wallet.
2. Send a small test amount.
3. Confirm that the transaction and balance appear correctly on all three wallets.

## 📤 Create, Sign, and Broadcast a Transaction

### 1. First Signature

Cosigner A:

1. Creates the transaction.
2. Verifies the recipient address, amount, miner fee, and change outputs.
3. Adds the first signature.
4. Exports the partially signed transaction.

Depending on the Electrum version, the exported data may be a PSBT or an Electrum transaction file.

### 2. Second Signature

Cosigner B:

1. Imports the partially signed transaction.
2. Independently verifies the recipient address, amount, miner fee, and change outputs.
3. Adds the second signature.

### 3. Broadcast

After the transaction contains two valid signatures, any cosigner can broadcast it to the Bitcoin network.

The partially signed transaction can be transferred using a transaction file, QR code, removable media, or another authenticated communication channel.

> ✅ Always verify transaction details inside Electrum on a trusted device before signing or broadcasting.

## 💻 Electrum Console Commands

Open the console from:

```text
View → Show Console
```

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

### Print Receiving Addresses

```python
print("\n".join(wallet.get_receiving_addresses()))
```

> ⚠️ The console is an advanced interface. Only run commands that you understand and obtained from a trusted source. Never paste a real seed phrase into commands provided by another person.

Electrum seeds use Electrum's own seed-version system and must not automatically be treated as BIP39 mnemonics.

## 🛡️ Security and Recovery

- Never share seed phrases, private keys, or wallet passwords.
- Never enter a real seed into a website, chat, email, cloud note, or untrusted application.
- Keep seed backups offline and in separate physical locations.
- Verify every `xpub` through an authenticated channel.
- An `xpub` cannot sign transactions, but it can reveal addresses, balances, and transaction history.
- Verify recipient addresses, amounts, fees, and change outputs before signing.
- Use trusted devices with disk encryption and current security updates.
- Test receiving, signing, broadcasting, and recovery with a small amount first.
- Record the **2-of-3 policy**, wallet type, script type, cosigner public keys, derivation information, and relevant Electrum version.
- Recovery and spending require valid signing material from at least two cosigners.

## 🔗 Official Wallet Resources

| Wallet | Official Website | GitHub Repository |
|---|---|---|
| ⚡ Electrum | https://electrum.org | https://github.com/spesmilo/electrum |
| 🛡️ Wasabi Wallet | https://wasabiwallet.io | https://github.com/WalletWasabi/WalletWasabi |
| 🐦 Sparrow Wallet | https://sparrowwallet.com | https://github.com/sparrowwallet/sparrow |

> 📌 Download wallet software only from its official website or verified GitHub repository. Check release signatures and package hashes when available.
