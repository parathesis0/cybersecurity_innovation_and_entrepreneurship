# Bitcoin Testnet4 交易构造、逐字节解析与区块验证

**网络安全创新创业课程作业 1**

  ----------------------------------------------------------------------------------------------
  **项目**       **内容**
  -------------- -------------------------------------------------------------------------------
  小组成员姓名   魏子彦 王佳琦 王国赫

  专业/班级      网安2班

  实验网络       Bitcoin Testnet4

  交易 txid      1dd070a132e4c5dd1ab2fde424b82903a53e6afa22b921d9448590b71a5bcda7

  确认区块       高度 144878，0000000000b9d2773b283332f6e1c36da7fdd7b11af12fa7f14866e0beb425ca

  完成日期       2026 年 7 月 20 日
  ----------------------------------------------------------------------------------------------

## 摘要

本报告完成课件要求的 Bitcoin 实践项目：使用 Sparrow Wallet 在 Bitcoin Testnet4 创建原生 SegWit（P2WPKH）钱包，从测试币水龙头获得 UTXO，构造、签名并广播一笔交易；随后以最终广播的原始交易 tx.txt 为唯一权威数据源，对 222 个字节逐字段解释，并用脚本验证 txid、wtxid、交易重量、手续费、BIP143 签名哈希、HASH160 公钥绑定和 secp256k1 ECDSA 签名。该交易已进入高度 144878 的 Testnet4 区块，脚本进一步解析完整 4045 字节区块，覆盖 80 字节区块头和全部 14 笔交易，并重算 PoW 目标、交易 Merkle 根与 SegWit witness commitment。

最终交易 txid 为 1dd070a132e4c5dd1ab2fde424b82903a53e6afa22b921d9448590b71a5bcda7，花费水龙头 UTXO 394,027 sats，向目标地址支付 114,514 sats，找零 277,258 sats，实际手续费 2,255 sats。交易重量为 561 WU，精确虚拟大小为 140.25 vB，因此最终费率约为 16.08 sat/vB，与实际使用的 16× 设置一致。所有自动核验项均通过。

**关键词：** Bitcoin；Testnet4；UTXO；SegWit；P2WPKH；BIP143；ECDSA；Merkle Tree；Proof of Work

## 1. 作业目标与完成情况

课件要求在 Bitcoin 测试网上发送一笔交易，将原始交易数据解析到每一个字节，并尝试用脚本解析完整区块、计算各字段。为使结果可核验，本报告把任务拆为交易流程、序列化解析、脚本执行、密码学验签和区块验证五部分。

  ---------------------------------------------------------------------------------------------------------------------------
  **要求**             **完成方式**                                                            **核验结果**
  -------------------- ----------------------------------------------------------------------- ------------------------------
  测试网发送交易       Sparrow Wallet 切换 Testnet4，接收测试币后构造、签名、广播              已在高度 144878 确认

  逐字节解析交易       脚本记录每个字段的绝对偏移、长度、原始十六进制和解释                    222/222 字节恰好覆盖一次

  解释锁定/解锁脚本    解析前序 P2WPKH witness program、空 scriptSig、签名与压缩公钥 witness   公钥哈希匹配，ECDSA 验签通过

  解析完整区块         解析区块头、CompactSize 交易数及全部 14 笔交易                          4045/4045 字节恰好覆盖一次

  重算关键密码学结果   重算 PoW、txid/wtxid、Merkle root、witness commitment                   全部与链上数据一致
  ---------------------------------------------------------------------------------------------------------------------------

安全说明：过程截图中的助记词属于钱包秘密，即使钱包仅用于测试网，也不应出现在可提交或公开传播的报告中。因此图 4 使用脱敏副本；原截图仍保留在本地 imgs 目录中，不在报告正文展示其内容。

## 2. 实验环境与交易流程

### 2.1 安装钱包并切换 Testnet4

实验使用 Sparrow Wallet 2.5.2。启动后通过 Tools → Restart In → Testnet4 切换到第四代 Bitcoin 测试网。Testnet4 与主网使用相同的交易、脚本和工作量证明数据结构，但测试币没有真实经济价值，适合完成交易构造实验。

![图 1 下载 Sparrow Wallet](media/image1.png)

![图 2 切换至 Testnet4](media/image2.png)

### 2.2 创建原生 SegWit 钱包

创建名为 Para wallet 的软件钱包，策略为 Single Signature HD，脚本类型选择 Native SegWit（P2WPKH），密钥派生遵循 BIP39/BIP84。BIP84 的典型 Testnet 派生路径为 m/84\'/1\'/account\'/change/address_index。钱包生成的 12 个助记词用于恢复私钥。

![图 3 创建钱包](media/image3.png)

![图 4 助记词页面](media/image4.png)

![图 5 应用 Native SegWit（P2WPKH）钱包策略](media/image5.png)

### 2.3 从水龙头获得测试 UTXO

钱包生成接收地址 tb1qmf694grlk9r6cyt296dt5wr50803cmxy6vn2p2。水龙头向该地址支付 394,027 sats；该资金在后续交易中作为唯一输入，引用前序交易 97afb394...337a6a 的 vout=1。

![图 6 获取接收地址](media/image6.png)

![图 7 Testnet4 水龙头转账](media/image7.png)

![图 8 钱包收到 394,027 sats](media/image8.png)

![图 9 首次确认通知](media/image9.png)

### 2.4 构造、签名与广播交易

交易向 tb1qerzrlxcfu24davlur5sqmgzzgsal6wusda40er 支付 114,514 sats，并把 277,258 sats 找零到钱包新地址 tb1qycpmmqv7evxsexkcsaz6kl730x84zamzcdgpaq。最终交易使用实际 16× 费率设置；过程截图中出现的旧费率报价只表示较早的界面状态，最终数值以 tx.txt 和链上交易为准。

![图 10 创建交易并设置收款地址与金额（税率实际约为16x）](media/image10.png)

![图 11 完成待签名交易](media/image11.png)

![图 12 由 BIP39 软件钱包签名](media/image12.png)

![图 13 广播已签名交易](media/image13.png)

![图 14 最终原始交易和 txid](media/image14.png)

## 3. 最终交易概览

  ------------------------------------------------------------------------------------------------
  **项目**                      **数值**
  ----------------------------- ------------------------------------------------------------------
  txid                          1dd070a132e4c5dd1ab2fde424b82903a53e6afa22b921d9448590b71a5bcda7

  wtxid                         7cf07f44093e8298477643bd9584e9063023abf881343056be21a7c50c8a4021

  版本 / nLockTime              2 / 144876（区块高度语义）

  输入 / 输出                   1 / 2

  总大小 / 基础大小 / witness   222 / 113 / 109 bytes

  重量 / vsize                  561 WU / 141 vB（精确 140.25 vB）

  输入金额 / 输出合计           394,027 / 391,772 sats

  手续费 / 实际费率             2,255 sats / 16.07843137 sat/vB

  确认区块                      高度 144878，交易索引 1
  ------------------------------------------------------------------------------------------------

fee = 394,027 − 114,514 − 277,258 = 2,255 sats

weight = base_size × 4 + witness_size = 113 × 4 + 109 = 561 WU

fee rate = 2,255 / (561 / 4) ≈ 16.0784 sat/vB

  -------------------------------------------------------------------------------------------------
  **类型**         **引用/序号**         **金额**       **脚本或地址**
  ---------------- --------------------- -------------- -------------------------------------------
  输入             97afb394...337a6a:1   394,027 sats   前序 P2WPKH：tb1qmf694...vn2p2

  输出 0（支付）   vout=0                114,514 sats   0014c8c43f...bfd3b90 / tb1qerzrl...da40er

  输出 1（找零）   vout=1                277,258 sats   00142603bd...517762 / tb1qycpmm...cdgpaq
  -------------------------------------------------------------------------------------------------

## 4. 原始交易逐字节解析

### 4.1 序列化顺序与大小端

Bitcoin 交易不是 JSON，而是紧凑的二进制串。整数通常按 little-endian 写入；交易哈希在原始数据中也按内部字节序出现，显示给用户时再反转。输入/输出数量和脚本长度使用 CompactSize。SegWit 交易在 version 后加入 marker=00、flag=01，并把 witness 放在全部输出之后、nLockTime 之前。

SegWit tx = version \|\| 00 \|\| 01 \|\| vin \|\| vout \|\| witness \|\| nLockTime

txid = reverse(SHA256d(stripped serialization))

wtxid = reverse(SHA256d(full SegWit serialization))

本交易的 stripped serialization 不含 marker、flag 和 witness，共 113 字节；完整序列化为 222 字节。因此 txid 与 wtxid 不同。逐字节脚本检查确认 offset 0 到 221 连续覆盖，没有遗漏或重叠。

### 4.2 位级语义

交易序列化的最小寻址单位是字节；所谓"到每一 bit"主要体现在标志位、操作码和前缀。下表把本交易中有明确位语义的字段进一步展开。

  ---------------------------------------------------------------------------------------------------
  **字段**       **原始值**     **二进制/位语义**
  -------------- -------------- ---------------------------------------------------------------------
  version        02 00 00 00    按 little-endian 解释为 32 位整数 2

  marker         00             00000000：提示采用扩展序列化

  flag           01             00000001：bit 0 表示存在 witness

  P2WPKH 长度    16             00010110₂ = 22 字节

  sequence       fd ff ff ff    0xfffffffd；bit31=1 禁用 BIP68 相对锁定，同时满足 BIP125 opt-in RBF

  witness 项数   02             00000010₂ = 2 项

  签名长度       47             01000111₂ = 71 字节

  公钥长度       21             00100001₂ = 33 字节

  公钥前缀       02             压缩公钥，表示 y 坐标为偶数

  sighash        01             SIGHASH_ALL；未设置 ANYONECANPAY

  nLockTime      ec 35 02 00    little-endian = 144876；小于 5×10⁸，按区块高度解释
  ---------------------------------------------------------------------------------------------------

### 4.3 完整字段表

下表列出 tx.txt 中全部字段。空 scriptSig 的长度为 0，因此它占用 0 个数据字节；长度字段本身仍占 1 字节。长签名和公钥保持完整十六进制，不做省略。

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **偏移**       **字节数**   **字段**                        **原始十六进制**                                                                                                                                 **解释**
  -------------- ------------ ------------------------------- ------------------------------------------------------------------------------------------------------------------------------------------------ ----------------------------------------------------------------------------------
  0 / 0x0000     4            version                         02000000                                                                                                                                         2 (32-bit little-endian)

  4 / 0x0004     1            marker                          00                                                                                                                                               0x00: extended/SegWit serialization marker

  5 / 0x0005     1            flag                            01                                                                                                                                               0x01: witness data present

  6 / 0x0006     1            input_count                     01                                                                                                                                               1

  7 / 0x0007     32           vin\[0\].prev_txid              6a7a335a0b2dee9d1378758ceee02d2bce5500992a854bc8673db4e894b3af97                                                                                 97afb394e8b43d67c84b852a990055ce2b2de0ee8c7578139dee2d0b5a337a6a (display order)

  39 / 0x0027    4            vin\[0\].prev_vout              01000000                                                                                                                                         1

  43 / 0x002b    1            vin\[0\].scriptSig_length       00                                                                                                                                               0

  44 / 0x002c    0            vin\[0\].scriptSig              \<empty\>                                                                                                                                        empty

  44 / 0x002c    4            vin\[0\].sequence               fdffffff                                                                                                                                         0xfffffffd; BIP125 RBF=yes; BIP68 relative lock disabled=yes

  48 / 0x0030    1            output_count                    02                                                                                                                                               2

  49 / 0x0031    8            vout\[0\].value                 52bf010000000000                                                                                                                                 114,514 sat = 0.00114514 BTC

  57 / 0x0039    1            vout\[0\].scriptPubKey_length   16                                                                                                                                               22

  58 / 0x003a    22           vout\[0\].scriptPubKey          0014c8c43f9b09e2aadeb3fc1d200da042443bfd3b90                                                                                                     P2WPKH, tb1qerzrlxcfu24davlur5sqmgzzgsal6wusda40er

  80 / 0x0050    8            vout\[1\].value                 0a3b040000000000                                                                                                                                 277,258 sat = 0.00277258 BTC

  88 / 0x0058    1            vout\[1\].scriptPubKey_length   16                                                                                                                                               22

  89 / 0x0059    22           vout\[1\].scriptPubKey          00142603bd819ecb0d0c9ad88745ab7fd1798f517762                                                                                                     P2WPKH, tb1qycpmmqv7evxsexkcsaz6kl730x84zamzcdgpaq

  111 / 0x006f   1            vin\[0\].witness.item_count     02                                                                                                                                               2

  112 / 0x0070   1            vin\[0\].witness\[0\].length    47                                                                                                                                               71

  113 / 0x0071   71           vin\[0\].witness\[0\]           3044022037462debb2cccf9d64623982195ea538e6ed24fe79b62aad41c328d49f1cb549022032954dd35fcaeb8fa015d442d0db092a2c6706e4d8433ced0edd62e46a0da69101   DER ECDSA signature followed by one-byte sighash type

  184 / 0x00b8   1            vin\[0\].witness\[1\].length    21                                                                                                                                               33

  185 / 0x00b9   33           vin\[0\].witness\[1\]           023080eb7885daed9fc54d3f5314672716c98679ccc0d0d690c4ad00a7930302e8                                                                               compressed public key; prefix=0x02

  218 / 0x00da   4            locktime                        ec350200                                                                                                                                         144876 (block height)
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 5. P2WPKH 锁定与解锁脚本

### 5.1 前序 UTXO 的锁定条件

本交易输入本身只保存"引用哪个 UTXO"，真正的锁定脚本来自被花费的前序输出。链上前序输出脚本为 0014da745aa07fb147ac116a2e9aba387479df1c6cc4：00 是 witness version 0，14 是 20 字节数据长度，后续 20 字节是公钥哈希。对应地址为 tb1qmf694grlk9r6cyt296dt5wr50803cmxy6vn2p2。

scriptPubKey = OP_0 \|\| PUSH20 \|\| HASH160(expected public key)

### 5.2 witness 解锁数据

由于是原生 P2WPKH，scriptSig 为空，解锁数据位于 witness。witness 有两项：第一项是 70 字节 DER 签名加 1 字节 SIGHASH_ALL，第二项是 33 字节压缩公钥。

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **witness 项**   **长度**   **内容**
  ---------------- ---------- ------------------------------------------------------------------------------------------------------------------------------------------------
  0                71         3044022037462debb2cccf9d64623982195ea538e6ed24fe79b62aad41c328d49f1cb549022032954dd35fcaeb8fa015d442d0db092a2c6706e4d8433ced0edd62e46a0da69101

  1                33         023080eb7885daed9fc54d3f5314672716c98679ccc0d0d690c4ad00a7930302e8
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------

验证先计算 HASH160(pubkey)。结果 da745aa07fb147ac116a2e9aba387479df1c6cc4 与前序 witness program 完全一致，证明 witness 公钥满足地址绑定；随后按 BIP143 计算签名消息并执行 CHECKSIG。

### 5.3 DER 签名与 BIP143 消息

签名结构为 30 44 02 20 \[r\] 02 20 \[s\] 01。30 表示 DER SEQUENCE，44 表示后续 DER 内容 68 字节；两个 02 20 分别表示 32 字节正整数 r 和 s；最后的 01 不属于 DER，而是 Bitcoin 的 SIGHASH_ALL 类型。

  ----------------------------------------------------------------------------------
  **项目**        **数值**
  --------------- ------------------------------------------------------------------
  r               37462debb2cccf9d64623982195ea538e6ed24fe79b62aad41c328d49f1cb549

  s               32954dd35fcaeb8fa015d442d0db092a2c6706e4d8433ced0edd62e46a0da691

  low-S           是，s ≤ n/2，满足 Bitcoin 标准化要求

  scriptCode      76a914da745aa07fb147ac116a2e9aba387479df1c6cc488ac

  BIP143 digest   69cbe0b2ddf0d3b96bf4ecb9f9a9c5291ac6ddf55848ef91b5c6d18a3808cc83

  ECDSA 结果      通过：Rₓ mod n = r
  ----------------------------------------------------------------------------------

z = SHA256d(nVersion \|\| hashPrevouts \|\| hashSequence \|\| outpoint \|\| scriptCode \|\| amount \|\| nSequence \|\| hashOutputs \|\| nLockTime \|\| hashType)

R = s⁻¹(zG + rP), verify if Rₓ mod n = r

脚本使用真实 secp256k1 曲线参数做纯 Python ECDSA 验证，不依赖钱包或区块浏览器的"已验证"结论。该校验通过，说明签名确由前序 UTXO 对应私钥产生，并且绑定了本交易的全部输入、sequence 和输出。

## 6. 完整区块解析与验证

### 6.1 区块头和 PoW

交易被打包进 Testnet4 高度 144878 的区块。完整区块原始数据为 4045 字节，其中区块头固定 80 字节，随后 1 字节 CompactSize 值 0e 表示 14 笔交易。区块时间为 2026-07-20 09:54:29 UTC。

  -------------------------------------------------------------------------------------------------------------------------------
  **偏移**   **长度**   **区块头字段**   **原始值**            **解释**
  ---------- ---------- ---------------- --------------------- ------------------------------------------------------------------
  0          4          version          0060bb31              0x31bb6000

  4          32         previous block   6d85af4f...00000000   0000000000e9ed9d48999d673d817cf089298e111083a71670cc7c6b4faf856d

  36         32         Merkle root      02d1ed18...b645358    5853640bbd50baf9df86ae513c514b856ba78e39933d2ea5fda3df2518edd102

  68         4          time             55f05d6a              2026-07-20 09:54:29 UTC

  72         4          bits             ffff001d              0x1d00ffff

  76         4          nonce            94023841              1094189716

  80         1          tx count         0e                    14
  -------------------------------------------------------------------------------------------------------------------------------

block_hash = reverse(SHA256d(80-byte header))

重算区块哈希得到 0000000000b9d2773b283332f6e1c36da7fdd7b11af12fa7f14866e0beb425ca，与链上区块哈希一致。bits=0x1d00ffff 解码出的目标为 00000000ffff0000...0000；把区块哈希视为大端整数后满足 hash ≤ target，因此 PoW 校验通过。

### 6.2 交易 Merkle 根

普通交易 Merkle 树以每笔交易的内部 txid 字节为叶子，相邻两项连接后做 SHA256d；当某层节点数为奇数时复制最后一项。14 个叶子最终得到的根为 5853640bbd50baf9df86ae513c514b856ba78e39933d2ea5fda3df2518edd102，与区块头完全一致。作业交易位于区块交易数组索引 1（coinbase 之后的第一笔普通交易）。

  -----------------------------------------------------------------------------------------------------------------------------
  **索引**      **txid**                                                           **size / weight / vsize**   **vin / vout**
  ------------- ------------------------------------------------------------------ --------------------------- ----------------
  0             be969c25b04d9a597bc64d5db15c8da829e7873f38dad96bca9196cbf9d6d7d2   188 B / 644 WU / 161 vB     1 / 2

  1（本作业）   1dd070a132e4c5dd1ab2fde424b82903a53e6afa22b921d9448590b71a5bcda7   222 B / 561 WU / 141 vB     1 / 2

  2             fde5e62c555e8a5fc931f1391e403a1c773b755fd036be559a86978a001ea375   222 B / 888 WU / 222 vB     1 / 2

  3             f1d34c37724860d3945a505e2e64866825f8b610cc578716096606ae20f4ec16   442 B / 1003 WU / 251 vB    1 / 4

  4             f9b0b9cd00d0f2360b85a74df0eace3ad93787af8edc36761ee585a507ca3156   380 B / 755 WU / 189 vB     1 / 2

  5             27cbd09a00f933ce483b7d115540863bad0fa24fbcf32830a481f51b59d28cdb   285 B / 1140 WU / 285 vB    1 / 4

  6             e129119062c69bde817a7546463da826b6d72af88cffe2f074641f0f50ba940b   285 B / 810 WU / 203 vB     1 / 4

  7             e4cddabf1a1c2e30ce85f3f6e3bb6e7689bb9b85255ab76b5edcf26f2b1a264c   222 B / 561 WU / 141 vB     1 / 2

  8             5172cd7da4628d94ee7a49a32b2accb2270a9a9dbb544675d3b531903a664d18   420 B / 1476 WU / 369 vB    1 / 7

  9             e787b58ad426b2d6ff4bae051aea8f3448d8cbe1bbd7fdaef535b923221dd657   420 B / 1476 WU / 369 vB    1 / 7

  10            26f92755408772dd51233a097952fecec1ed63e994efe227444ad7992d46a68b   205 B / 616 WU / 154 vB     1 / 2

  11            f475e7630b28642e044a996486a42d631ce2c4b15439671dafff7d0f96204ee3   205 B / 616 WU / 154 vB     1 / 2

  12            30359f361a3d9e3a683416fdd668c0d360131734194fc81743caf5bf205ef1ea   205 B / 616 WU / 154 vB     1 / 2

  13            4aa330ae4ecf52c82f38d22149b2b7da79f928e1cdad47bb33b553c093a25f7a   263 B / 1001 WU / 251 vB    5 / 1
  -----------------------------------------------------------------------------------------------------------------------------

### 6.3 SegWit witness commitment

SegWit 区块还必须承诺 witness 数据。计算时把 coinbase 的 wtxid 设为 32 字节全零，其余交易使用 wtxid 构造 witness Merkle 树；再与 coinbase witness 中的 32 字节 reserved value 连接并 SHA256d。

commitment = SHA256d(witness_merkle_root \|\| witness_reserved_value)

  -------------------------------------------------------------------------------------------------------
  **项目**                             **计算值**
  ------------------------------------ ------------------------------------------------------------------
  witness Merkle root                  ebefd9ba38fccc137df56ebfcffc49a47772473c877d2649a6b4f65d5c765702

  reserved value                       0000000000000000000000000000000000000000000000000000000000000000

  计算 commitment                      b02575db4df1787cd461c96dbb9bfcf86a9c4fa1780b1c35639149db0182e65c

  coinbase OP_RETURN 中的 commitment   b02575db4df1787cd461c96dbb9bfcf86a9c4fa1780b1c35639149db0182e65c

  结果                                 完全一致，witness commitment 校验通过
  -------------------------------------------------------------------------------------------------------

### 6.4 完整区块字节覆盖

脚本从 offset 0 开始顺序读取区块头、交易数和 14 笔交易的 version、vin、vout、witness、locktime，最终 reader offset 恰为 4045。基础大小为 2814 字节，总重量 12487 WU，vsize 3122 vB。evidence/block_parse.txt 保留完整 43 KB 字段清单，逐行给出 offset、长度、字段路径、完整十六进制和解释，从而证明 4045/4045 字节恰好覆盖一次。

Coinbase 的 BIP34 高度解码为 144878；其首个输出为 5,000,011,515 sats，即 50 BTC 区块补贴加本区块总手续费 11,515 sats。第二个 0 sat OP_RETURN 输出携带 witness commitment。

## 7. 自动化脚本与复现结果

scripts/parse_bitcoin.py 仅使用 Python 标准库，包含 CompactSize、SegWit 交易、常见 scriptPubKey、DER、secp256k1 ECDSA、Merkle 树和 compact target 实现。它读取 tx.txt、metadata.json 和 block-144878.hex，生成两份证据报告。

    cd assignment-1
    python .\scripts\parse_bitcoin.py

  -----------------------------------------------------------------------
  **自动核验项**                           **结果**
  ---------------------------------------- ------------------------------
  txid / wtxid                             PASS / PASS

  BIP143 ECDSA signature                   PASS

  block hash / BIP34 height                PASS / PASS

  proof of work                            PASS

  transaction Merkle root                  PASS

  SegWit witness commitment                PASS

  交易位于区块中                           PASS

  222 字节交易覆盖                         PASS

  4045 字节区块覆盖                        PASS
  -----------------------------------------------------------------------

evidence/tx_parse.txt 是交易解析与签名验证的可读输出；evidence/block_parse.txt 是完整区块字段表；evidence/block-144878.hex 保存可离线复现的区块原始数据。

## 8. 结论

本实验从钱包界面一直追踪到共识数据结构。Sparrow Wallet 展示的"收款、找零、手续费"最终都落为确定的 little-endian 整数和脚本字节；地址不是链上字段，而是 witness program 的人类可读 Bech32 编码；P2WPKH 的所有权证明不在 scriptSig，而在 witness 的签名与公钥中；txid 为兼容旧系统排除 witness，wtxid 和 coinbase witness commitment 则把 witness 纳入区块承诺。

最终交易的 222 字节、所在区块的 4045 字节均得到无遗漏解析。交易金额守恒、BIP143 摘要、ECDSA 签名、PoW、交易 Merkle 根和 witness commitment 全部通过独立重算。由此可见，Bitcoin 的安全不是单一签名算法的结果，而是 UTXO 引用、脚本条件、序列化规则、哈希承诺和工作量证明共同构成的可验证链条。

## 参考资料

Satoshi Nakamoto, Bitcoin: A Peer-to-Peer Electronic Cash System, 2008.

Bitcoin Developer Reference, Transactions and Block Chain data structures.

BIP 34: Block v2, Height in Coinbase.

BIP 125: Opt-in Full Replace-by-Fee Signaling.

BIP 141: Segregated Witness (Consensus layer).

BIP 143: Transaction Signature Verification for Version 0 Witness Program.

BIP 173: Base32 address format for native v0-16 witness outputs.

BIP 84: Derivation scheme for P2WPKH based accounts.

Sparrow Wallet Documentation, https://sparrowwallet.com/docs/

mempool.space Testnet4 API, transaction and block raw data.

## 附录 A：最终原始交易

    020000000001016a7a335a0b2dee9d1378758ceee02d2bce5500992a854bc867
    3db4e894b3af970100000000fdffffff0252bf010000000000160014c8c43f9b
    09e2aadeb3fc1d200da042443bfd3b900a3b0400000000001600142603bd819e
    cb0d0c9ad88745ab7fd1798f51776202473044022037462debb2cccf9d646239
    82195ea538e6ed24fe79b62aad41c328d49f1cb549022032954dd35fcaeb8fa0
    15d442d0db092a2c6706e4d8433ced0edd62e46a0da6910121023080eb7885da
    ed9fc54d3f5314672716c98679ccc0d0d690c4ad00a7930302e8ec350200

## 附录 B：证据文件索引

  --------------------------------------------------------------------------
  **文件**                    **用途**
  --------------------------- ----------------------------------------------
  tx.txt                      最终广播交易的 222 字节原始十六进制

  scripts/parse_bitcoin.py    逐字节解析和密码学验证脚本

  evidence/metadata.json      链上前序输出、确认区块和最终费率元数据

  evidence/tx_parse.txt       完整交易字段表、BIP143 摘要和 ECDSA 结果

  evidence/block-144878.hex   包含该交易的完整 Testnet4 区块原始数据

  evidence/block_parse.txt    完整区块逐字段解析与 PoW/Merkle/witness 验证

  imgs/                       实验过程截图；助记词副本在报告中已脱敏
  --------------------------------------------------------------------------
