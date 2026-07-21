# libsecp256k1 安全修复与性能优化研究

**网络安全创新创业课程作业 2**

| 项目 | 内容 |
|------|------|
| 学生姓名 | 魏子彦 王佳琦 王国赫 |
| 专业/班级 | 网安2班 |
| 仓库 | `bitcoin-core/secp256k1` |
| 调研版本 | `8c3e6e6d992456d3b9228305ae84a6703273cf70` |
| 完成日期 | 2026 年 7 月 20 日 |

------------------------------------------------------------------------

## 摘要

本报告以 Bitcoin Core 使用的高性能椭圆曲线密码库 `libsecp256k1` 为对象，结合仓库源代码、提交历史、发布日志和本机实验，研究密码实现中的两类核心问题：安全修复与性能优化。安全部分首先推导课件中"验证者不自行检查被签消息时，可伪造 ECDSA 签名"的数学过程，并用真实 secp256k1 参数完成无第三方依赖的实验；随后分析仓库对该 API 误用的文档加固、RFC 6979 消息归约修复、Clang/GCC 破坏常数时间性质的修复，以及 x86_64 内联汇编 early-clobber 约束错误。性能部分分析 ECDSA 验证中避免有限域求逆、基于 safegcd 的模逆、GLV 内自同态与有符号数字常数时间点乘、固定基点 multi-comb 乘法，以及删除已经落后于现代编译器的手写有限域汇编。

研究表明，密码工程中的"正确"不只指公式正确。调用者是否绑定了正确消息、编译器是否保持常数时间、汇编约束是否准确、坐标表示是否避免昂贵求逆，都会影响最终安全性或性能。`libsecp256k1` 的演进还体现出一个重要工程结论：代码简化、安全审计与加速并不冲突；删除脆弱汇编、缩小预计算表和使用可证明的代数变换，有时能够同时得到更小、更快、更容易审查的实现。

**关键词：** Bitcoin；secp256k1；ECDSA；Schnorr；常数时间；RFC 6979；safegcd；GLV；multi-comb

## 1. 作业目标与调研方法

课件给出的项目要求是检查 [`bitcoin-core/secp256k1`](https://github.com/bitcoin-core/secp256k1) 仓库，撰写与 Bitcoin 密码算法使用有关的缺陷修复、性能提升报告，并解释"为什么"和背后的数学。本报告将"完整完成"具体化为以下可核验目标：

1.  解释课件标题所指的 ECDSA 选定哈希伪造，而不把它误写成私钥恢复或任意消息伪造。
2.  从真实 Git 历史选择安全与性能案例，给出提交哈希、代码变化、风险范围和数学理由。
3.  区分共识验证、钱包签名、密钥交换及网络传输等不同使用场景，避免夸大影响。
4.  构建当前仓库、运行完整测试和基准，并保留可复现脚本与实验代码。

本地仓库核验结果如下：

| 项目 | 核验结果 |
|------|----------|
| 远程仓库 | `https://github.com/bitcoin-core/secp256k1` |
| 分支 | `master` |
| HEAD | `8c3e6e6d992456d3b9228305ae84a6703273cf70` |
| 可达提交数 | 2800 |
| 最新发布标签 | `v0.7.1` |
| 当前仓库状态日期 | HEAD 提交日期为 2026-07-18，本报告核验于 2026-07-20 |

证据优先级为：源代码与提交差异 \> 合并提交/发布说明 \> 本机测试 \> 二手解释。报告引用的相对性能数字均来自上游合并提交或变更日志；本机绝对耗时单独列出，不将不同机器的数字混为一谈。

## 2. Bitcoin 中的 secp256k1 密码组件

### 2.1 曲线与密钥

secp256k1 是定义在素域 $\mathbb{F}_{p}$ 上的短 Weierstrass 曲线：

$$y^{2} = x^{3} + 7\ (mod\ p),$$

其中

$$p = 2^{256} - 2^{32} - 977.$$

标准基点为 $G$，其生成子群的素数阶为

$$n = \text{FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141}_{16}.$$

私钥是 $d \in \{ 1,\ldots,n - 1\}$，公钥是 $P = dG$。安全性依赖椭圆曲线离散对数问题：已知 $G$ 和 $P$ 时，计算 $d$ 在可行计算资源下应当不可行。

实现中存在两个不同的模数，不能混淆：

- 点坐标运算在有限域模 $p$ 下进行；
- 私钥、随机数和签名标量在群阶模 $n$ 下进行。

仓库因而分别实现 field element 与 scalar，并针对 64 位平台采用 5×52 位域表示、4×64 位标量表示；32 位路径则使用 10×26 和 8×32 表示。

### 2.2 算法与 Bitcoin 场景

当前仓库提供 ECDSA、BIP 340 Schnorr、ECDH、BIP 324 ElligatorSwift XDH 和 BIP 327 MuSig2 等模块。它们与 Bitcoin 的关系并不完全相同：

| 功能 | 主要运算 | Bitcoin 场景 | 安全数据是否为秘密 |
|------|----------|--------------|-------------------|
| ECDSA 签名 | $kG$、$k^{- 1}$ | 钱包签署传统及 SegWit v0 输入 | 私钥 $d$、nonce $k$ 是秘密 |
| ECDSA 验证 | $u_{1}G + u_{2}P$ | 脚本/交易验证 | 输入均为公开数据，可使用 variable-time 算法 |
| BIP 340 Schnorr | 固定基点乘法、双标量乘法、Tagged Hash | Taproot/SegWit v1 | 签名路径含秘密，验证路径公开 |
| ECDH | $dP$ | 通用密钥协商能力 | 标量 $d$ 是秘密，必须常数时间 |
| ElligatorSwift XDH | 隐蔽编码与 $dP$ | BIP 324 P2P v2 传输密钥协商 | 本地密钥是秘密 |
| MuSig2 | 聚合公钥、nonce 与部分签名 | BIP 327 多签协议能力 | nonce/部分签名状态高度敏感 |

模块存在于库中不等于它已经成为 Bitcoin 共识规则。例如 MuSig2 是协议工具，而 ECDSA 与 BIP 340 验证直接关系交易有效性；普通 ECDH 模块的侧信道修复也不能简单表述为"攻击者能伪造链上交易"。准确的影响说明应指出攻击面属于共识正确性、钱包密钥保密性还是网络会话保密性。

## 3. ECDSA 数学与课件中的伪造

### 3.1 正常签名与验证

设消息摘要转换成标量 $e$。签名者随机选择或确定性地产生 $k \in \mathbb{Z}_{n}^{*}$，计算

$$R = kG,\quad\quad r = x_{R}\ mod\ n,$$

$$s = k^{- 1}(e + rd)\ mod\ n.$$

签名为 $(r,s)$。验证者计算

$$w = s^{- 1}\ mod\ n,\quad\quad u_{1} = ew,\quad\quad u_{2} = rw,$$

$$R' = u_{1}G + u_{2}P.$$

对合法签名，利用 $P = dG$ 和 $s = k^{- 1}(e + rd)$：

$$R' = s^{- 1}(eG + rP) = s^{- 1}(e + rd)G = kG = R.$$

因此检查 $x_{R'}\ mod\ n = r$ 即可。

### 3.2 如果验证者直接接受攻击者给出的哈希

课件中的攻击不是求出 $d$，而是攻击者同时构造"摘要"和签名。任选 $u,v \in \mathbb{Z}_{n}^{*}$，计算

$$R' = uG + vP = (x',y'),\quad\quad r' = x'\ mod\ n.$$

然后令

$$e' = r'uv^{- 1}\ mod\ n,$$

$$s' = r'v^{- 1}\ mod\ n.$$

因为

$$(s')^{- 1}e' = u,\quad\quad(s')^{- 1}r' = v,$$

验证者重算的点恰好是

$$(s')^{- 1}(e'G + r'P) = uG + vP = R',$$

所以 $(r',s')$ 对"被共同构造的摘要 $e'$"验证成功，全程不需要私钥。

### 3.3 为什么这不等于任意消息伪造

攻击者得到的是一个代数上随机的 $e'$。若目标是预先选定的消息 $M$，仍需满足

$$H(M)\ mod\ n = e'.$$

对理想 256 位哈希，这相当于寻找原像，复杂度约为 $2^{256}$。因此：

- 若 API 调用者自行对准确的消息/交易上下文计算哈希，攻击失败；
- 若应用让攻击者同时提交 `msghash32` 和签名，然后只调用 ECDSA 验证，攻击成功；
- 这不是 ECDSA 私钥恢复，也不是对标准"消息先哈希"安全模型的直接攻破，而是 API 语义绑定失败。

Bitcoin 的签名检查必须先按照具体 sighash 规则，从交易版本、输入、输出、金额、脚本、序号和 sighash 类型等上下文构造确定的摘要，再把该摘要传给曲线库。通用曲线库无法替调用者决定 Bitcoin 的交易序列化和脚本语义，所以消息绑定必须由上层完成。

### 3.4 与 low-S 可塑性的区别

ECDSA 还有另一个容易混淆的问题：若 $(r,s)$ 有效，则 $(r,n - s)$ 也有效。后者使验证点变成 $- R$，但 $R$ 与 $- R$ 的横坐标相同。因此 `libsecp256k1` 只接受 $s \leq n/2$ 的 lower-S 签名，以消除这一显然的签名可塑性。

选定哈希伪造与 high-S/low-S 的差别是：

- 选定哈希攻击构造新的 $e,r,s$，根因是验证者没有绑定真实消息；
- high-S 变换在同一消息、同一 $r$ 下得到第二个 $s$，根因是点 $R$ 的符号未编码进 ECDSA 签名。

实验脚本在必要时把 $s$ 归一化成 $n - s$，仍能通过验证，说明 lower-S 并不能修复"接受外部哈希"的 API 误用。

## 4. 安全修复案例

### 4.1 案例一：把 `msg32` 明确为 `msghash32`

**提交：** [`f587f04e35719883546afd54cb491ead18eb6fc7`](https://github.com/bitcoin-core/secp256k1/commit/f587f04e35719883546afd54cb491ead18eb6fc7)，2020-12-03。

该提交把 ECDSA 签名/验证 API 参数从含义模糊的 `msg32` 重命名为 `msghash32`，并在 `secp256k1_ecdsa_verify` 文档中明确警告：验证者必须自行对消息应用密码哈希，不能直接接受外部提供的 `msghash32`，否则可在不知道私钥的情况下构造有效签名。

这不是曲线公式的代码修复，而是安全接口修复。其必要性来自职责边界：

1.  库只接收 32 字节，无法判断它来自 SHA-256、Bitcoin sighash，还是攻击者任意填写的整数。
2.  直接在库内"帮用户哈希"也不正确，因为 Bitcoin 不只是简单计算 `SHA256(message)`，不同签名版本有不同交易上下文和域分离规则。
3.  参数命名和文档属于安全机制的一部分。密码库若容易被正确调用但同样容易被危险调用，就仍有现实风险。

当前头文件保留了这一警告，且内容与课件攻击完全对应。这是本作业图片与仓库历史之间最直接的联系。

更强的应用层做法是不要暴露"验证任意 32 字节哈希"的公共业务接口，而是使用带类型的函数，例如 `verify_transaction_signature(transaction, input_index, prevout, signature, pubkey)`，在函数内部产生 sighash。

### 4.2 案例二：RFC 6979 必须对消息表示做 `bits2octets`

**提交：** [`45f37b650635e46865104f37baed26ef8d2cfb97`](https://github.com/bitcoin-core/secp256k1/commit/45f37b650635e46865104f37baed26ef8d2cfb97)，2022-01-17；收录于 v0.2.0。

ECDSA 若复用 nonce $k$，或 $k$ 可预测，会直接泄露私钥。两个使用同一 $k$ 的签名满足

$$s_{1} = k^{- 1}(e_{1} + rd),\quad\quad s_{2} = k^{- 1}(e_{2} + rd),$$

所以

$$k = (e_{1} - e_{2})(s_{1} - s_{2})^{- 1}\ mod\ n,$$

进而

$$d = (s_{1}k - e_{1})r^{- 1}\ mod\ n.$$

RFC 6979 使用 HMAC-DRBG，从私钥与消息摘要确定性地产生 $k$，避免依赖每次签名时的外部随机数质量。标准 3.2(d) 不是直接输入原始摘要字节，而是输入

$$bits2octets(H_{1}) = int2octets(bits2int(H_{1})\ mod\ n).$$

修复前，库把 API 的原始 32 字节 `msg32` 直接喂给 RFC 6979 状态；修复后，先通过 scalar 解析归约到模 $n$，再序列化为 32 字节。对正常且小于 $n$ 的摘要两者相同；对攻击者构造的 `n+1`，标准表示应与 `1` 相同，而旧实现不同。

对均匀 SHA-256 输出，摘要大于等于 $n$ 的概率为

$$\frac{2^{256} - n}{2^{256}} \approx 3.7345 \times 10^{- 39} \approx 2^{- 127.65}.$$

因此变更日志指出它只影响对签名 API 的不当使用：真实哈希碰到该区间的概率可忽略，但 API 允许调用者提供任意 32 字节，测试向量和跨实现一致性仍应严格符合标准。该修复的价值是规范一致性和对恶意/非标准输入的确定行为，不应夸大成"此前正常 Bitcoin 签名普遍泄露私钥"。

随附 `rfc6979_reduction_demo.py` 实际展示了旧输入方式和标准归约方式对 `n+1` 产生不同 nonce，而修复后的 `n+1` 与 `1` 产生相同 nonce。

### 4.3 案例三：编译器把常数时间选择重新变成分支

**核心提交：**

- [`4a496a36fb07d6cc8c99e591994f4ce0c3b1174c`](https://github.com/bitcoin-core/secp256k1/commit/4a496a36fb07d6cc8c99e591994f4ce0c3b1174c)，Clang 15 条件移动修复，v0.3.1。
- [`5fb336f9ce7d287015ada5d1d6be35d63469c9a4`](https://github.com/bitcoin-core/secp256k1/commit/5fb336f9ce7d287015ada5d1d6be35d63469c9a4) 与 [`17fa21733aae97bf671fede3ce528c7a3b2f5f14`](https://github.com/bitcoin-core/secp256k1/commit/17fa21733aae97bf671fede3ce528c7a3b2f5f14)，扩展到 `scalar_cond_negate`、模逆 divsteps 和点乘表选择，v0.3.2。

密码实现中的常数时间要求不是"每次耗时绝对相等"，而是控制流、内存访问地址和指令序列不能依赖秘密。典型条件移动希望用掩码实现：

$$\text{mask} = \left\{ \begin{matrix}
0, & flag = 0, \\
2^{w} - 1, & flag = 1,
\end{matrix} \right.\ $$

$$r = (r \land \neg\text{mask}) \vee (a \land \text{mask}).$$

源代码没有 `if (flag)` 并不保证机器代码没有分支。Clang 15 识别出掩码的高级语义后，曾把有限域/标量的 `cmov` 优化回条件跳转。若 `flag` 来自私钥位、nonce 位或秘密点乘的符号，分支预测状态、执行时间或缓存行为可能泄露秘密信息。

快速修复把条件复制到 `volatile` 局部变量，再生成掩码，阻止当时编译器完成这一危险重写。例如 5×52 有限域实现从使用 `flag` 变为使用 `volatile int ``vflag`` = flag`。v0.3.2 又对 GCC 13.1 暴露的 ECDH 路径做更保守处理；发布日志明确建议使用 GCC 13.1 的 ECDH 用户升级，因为秘密相关控制流可能产生计时侧信道。

该案例有三个重要结论：

1.  **编译器属于可信计算基。** C 代码审查通过后，升级编译器仍可能改变侧信道性质。
2.  `volatile` **是针对工具链行为的工程屏障，不是形式化常数时间语言。** 所以项目还需要 `ctime_tests.c`、Valgrind 未定义值跟踪、反汇编审查和新编译器快照 CI。
3.  **签名与验证可以采用不同时间模型。** 验证数据公开，可用 variable-time 模逆和点乘；签名、私钥生成和 ECDH 的秘密标量路径必须避免数据相关分支与索引。

v0.4.0 开始测试未发布的 GCC/Clang 快照，正是为了更早发现由编译器引入的常数时间回归。

### 4.4 案例四：x86_64 内联汇编输出缺少 early-clobber

**提交：** [`0c729ba70d963f2798184b0b8524d7de2f3ced9f`](https://github.com/bitcoin-core/secp256k1/commit/0c729ba70d963f2798184b0b8524d7de2f3ced9f)，2023-05-12；v0.3.2。

标量乘法产生最多 512 位中间值，之后必须模群阶 $n$ 归约到 256 位。旧 x86_64 汇编约束把前三个输出声明为 `=g`。但汇编在读完输入指针 RSI 之前就写这些输出，编译器理论上可以让某个输出与 RSI 共用位置，导致输入尚未读取就被覆盖。

修复将约束改为 `=&g`。其中 `&` 表示 early-clobber：该输出在所有输入读取完成前可能被写，不能与任何输入重叠。问题的数学算法没有错，错的是 C 编译器与汇编之间的寄存器分配契约。发布日志说明理论后果可能是错误汇编、崩溃或读取无关内存，但当时未在实际编译器上观察到触发。

这类问题说明手写汇编的风险不只在指令逻辑：输入/输出约束、clobber 列表、调用约定、编译器版本都必须正确。后文"移除有限域手写汇编"的性能优化因此也同时降低了审计复杂度。

## 5. 性能优化案例

### 5.1 ECDSA 验证：在 Jacobian 坐标中比较，避免有限域求逆

**提交：** [`ce7eb6fb3de49a51286bf3d74175473dbd4458f9`](https://github.com/bitcoin-core/secp256k1/commit/ce7eb6fb3de49a51286bf3d74175473dbd4458f9)，2014-11-29；解释提交 [`13278f642ccf58ed3e1ca7c97b97b52778f1b2e4`](https://github.com/bitcoin-core/secp256k1/commit/13278f642ccf58ed3e1ca7c97b97b52778f1b2e4)。

椭圆曲线点加在 affine 坐标中频繁需要求逆。Jacobian 坐标用 $(X:Y:Z)$ 表示 affine 点

$$x = X/Z^{2},\quad\quad y = Y/Z^{3}.$$

ECDSA 验证得到 Jacobian 点 `pr` 后，朴素方法先计算 $Z^{- 1}$，恢复 affine 横坐标，再做模 $n$ 比较。有限域求逆比乘法昂贵得多。

设签名给出的标量为 $r$，实际横坐标 $x < p$。因为 $2n > p$，满足 $x\ mod\ n = r$ 时只可能有两种情况：

$$x = r\quad\text{或}\quad x = r + n < p.$$

而 $x = X/Z^{2}$，所以可把等式两边乘 $Z^{2}$：

$$rZ^{2} \equiv X\ (mod\ p),$$

或在 $r + n < p$ 时检查

$$(r + n)Z^{2} \equiv X\ (mod\ p).$$

这样只需有限域乘法和比较，无需求逆。该优化直接位于 `src``/``ecdsa_impl.h` 的验证路径，是"用代数等价变换替换昂贵运算"的典型案例。它尤其有利于区块同步和 mempool 中的大量签名验证。

### 5.2 safegcd：快速且可常数时间的模逆

**合并提交：** [`26de4dfeb1f1436dae1fcf17f57bdaa43540f940`](https://github.com/bitcoin-core/secp256k1/commit/26de4dfeb1f1436dae1fcf17f57bdaa43540f940)，2021-03-17；后续半整数 $\delta$ 优化 [`efad3506a8937162e8010f5839fdf3771dfcf516`](https://github.com/bitcoin-core/secp256k1/commit/efad3506a8937162e8010f5839fdf3771dfcf516)。

ECDSA 签名需要 $k^{- 1}\ mod\ n$，验证需要 $s^{- 1}\ mod\ n$，坐标归一化需要域元素的 $z^{- 1}\ mod\ p$。模逆因而是关键基础操作。

若 $gcd(x,M) = 1$，扩展欧几里得算法能找到 $a,b$ 使

$$ax + bM = 1,$$

于是 $a = x^{- 1}\ mod\ M$。safegcd 把 GCD 过程重写为只依赖低位和状态 $\delta$ 的 divsteps。每一步在不改变 GCD 的前提下，对 $(f,g)$ 做类似

$$(f,g) \leftarrow \left( g,\frac{g - f}{2} \right),$$

$$(f,g) \leftarrow \left( f,\frac{g + f}{2} \right),$$

或

$$(f,g) \leftarrow \left( f,\frac{g}{2} \right).$$

实现同时维护系数 $d,e$，满足

$$d \equiv f/x\ (mod\ M),\quad\quad e \equiv g/x\ (mod\ M).$$

当 $g = 0$ 且 $|f| = 1$ 时即可恢复逆元。

高性能的关键是把 $N$ 个 divsteps 合并成一个 2×2 整数矩阵：

$$\begin{bmatrix}
f' \\
g'
\end{bmatrix} = 2^{- N}\begin{bmatrix}
u & v \\
q & r
\end{bmatrix}\begin{bmatrix}
f \\
g
\end{bmatrix}.$$

接下来 $N$ 步只依赖 $f,g$ 的低 $N$ 位，因此可先用机器字算出矩阵，再批量更新完整多精度数。常数时间版本使用固定轮数；采用初始 $\delta = 1/2$ 的改进后，256 位输入的证明上界降到 590 个 divsteps。variable-time 版本则可利用公开输入提前结束。

该合并还移除了 GMP 依赖，并为 field/scalar 同时提供 32 位和 64 位实现。当前本机基准中：

| 操作 | 平均耗时 |
|------|----------|
| `scalar_inverse`（常数时间） | 约 2.34 μs |
| `scalar_inverse_var` | 约 1.48 μs |
| `field_inverse`（常数时间） | 约 2.37 μs |
| `field_inverse_var` | 约 1.54 μs |

variable-time 更快是预期结果，但只能用于公开值。库在 ECDSA 验证中对公开 $s$ 使用 `scalar_inverse_var`，在签名中对秘密 $k$ 使用常数时间 `scalar_inverse`，体现了安全模型与性能之间的精确分工。

### 5.3 随机基点常数时间乘法：有符号数字与 GLV

**主要合并：**

- [`a1102b12196ea27f44d6201de4d25926a2ae9640`](https://github.com/bitcoin-core/secp256k1/commit/a1102b12196ea27f44d6201de4d25926a2ae9640)：简化 ECDH skew 修正，上游测得约 5% 提升。
- [`40f50d0fbd3c7ee78b4055bc6ca81027025c4148`](https://github.com/bitcoin-core/secp256k1/commit/40f50d0fbd3c7ee78b4055bc6ca81027025c4148)：有符号数字 `ecmult_const`，上游测得约 2% 提升。

ECDH 需要计算秘密标量乘任意公开点 $qA$。普通 double-and-add 若按标量位决定"是否加点"，会泄露秘密位，因此 `ecmult_const` 必须固定操作结构。

secp256k1 具有高效 GLV 内自同态 $\phi$，使

$$\phi(A) = \lambda A$$

可通过廉价坐标变换得到。标量可分解为

$$q = q_{1} + \lambda q_{2}\ (mod\ n),$$

其中 $q_{1},q_{2}$ 约为 128 位。于是

$$qA = q_{1}A + q_{2}\phi(A),$$

把一条 256 位乘法转换为两条可并行处理的半长度乘法。

新算法再把标量位解释为正负号。定义

$$C_{l}(v,A) = \sum_{i = 0}^{l - 1}(2v_{i} - 1)2^{i}A,$$

其中 $v_{i} \in \{ 0,1\}$，则

$$C_{l}(v,A) = (2v + 1 - 2^{l})A.$$

代码选择变换 $s = f(q)$，经 GLV 分解后给两个结果分别加 $2^{128}$，把它们放入非负 129 位范围，再按固定大小分组，从 $A$ 和 $\lambda A$ 的奇数倍表中常数时间选择点。合并提交给出的函数为

$$f(q) = \frac{q + (1 + \lambda)(2^{l} - 2^{129} - 1)}{2}\ (mod\ n).$$

与旧 fixed-wNAF 路径相比，新方法不再需要末尾的 skew 修正，表索引计算更简单，表大小也可独立调优。早期 ECDH 优化把 skew 从 1/2 改成 0/1，并在 global-Z 修正前用 Jacobian 条件移动完成修正，避免一次昂贵求逆，因此得到更明显的约 5% 提升。

### 5.4 固定基点乘法：signed-digit multi-comb

**合并提交：** [`da515074e3ebc8abc85a4fff3a31d7694ecf897b`](https://github.com/bitcoin-core/secp256k1/commit/da515074e3ebc8abc85a4fff3a31d7694ecf897b)，核心提交 [`fde1dfcd8d0a2a6444491b235d9ae2926f4ad7f4`](https://github.com/bitcoin-core/secp256k1/commit/fde1dfcd8d0a2a6444491b235d9ae2926f4ad7f4)，进入 v0.5.0。

ECDSA/Schnorr 签名和公钥生成都需要 $aG$。基点 $G$ 固定，适合用更大的预计算表换取少量在线加法。

算法定义

$$comb(s,P) = \sum_{i = 0}^{B - 1}(2s_{i} - 1)2^{i}P = (2s - (2^{B} - 1))P.$$

实现不直接做模 2 除法，而是使用 $G/2$，并把常量偏移预先放入上下文：

$$d = a + \text{scalar\_offset}\ (mod\ n),$$

$$aG = comb(d,G/2) + \text{ge\_offset}.$$

`ge_offset``=``bG` 与 `scalar_offset``=(2^B-1)/2-b` 还实现标量盲化：在线计算处理的是 $a - b$ 的等价形式，中间 Jacobian 坐标另有投影盲化，从而增加差分功耗/侧信道攻击难度。

multi-comb 用三个配置参数：块数 $B_{c}$、每表同时覆盖的 teeth 数 $T$、间隔

$$S = \left\lceil \frac{256}{B_{c}T} \right\rceil.$$

预计算表大小约为

$$B_{c} \cdot 2^{T - 1} \cdot 64\ \text{bytes},$$

在线点加数为 $B_{c}S$，倍点数为 $S - 1$。当前本机构建采用 86 KiB 表，即 $B_{c} = 43,T = 6,S = 1$：

$$43 \times 2^{5} \times 64 = 88064\ \text{bytes} \approx 86\ \text{KiB},$$

需要 43 次点加且不需要循环倍点。22 KiB 配置约为 $B_{c} = 11,T = 6,S = 4$，表更小，但需约 44 次点加和 3 次倍点。这清楚体现了内存与速度的可调权衡。

上游审查者在 GCC 13.2.0 测得约 12.4% 提升，在 Clang 15.0.0 测得约 11.5% 提升。与此同时，生成的预计算源文件和总体代码显著缩小，说明算法结构改进可以同时提高速度和可审计性。

### 5.5 删除有限域手写 x86_64 汇编反而更快

**提交：** [`2f0762fa8fd30b457bc5dcf53403123212091df5`](https://github.com/bitcoin-core/secp256k1/commit/2f0762fa8fd30b457bc5dcf53403123212091df5)，2023-11-23；v0.4.1。

该提交删除了约 500 行手写 5×52 有限域乘法/平方汇编。原因不是放弃优化，而是现代 GCC/Clang 的 `-O2` 输出已经超过旧手写实现。提交记录给出的 GCC 10.5.0 结果为：

- `fe_mul` 提升超过 20%；
- `secp256k1_ecdsa_verify` 和 `secp256k1_schnorrsig_verify` 提升超过 10%。

为什么有限域乘法会影响签名验证？点加、倍点和 Jacobian 比较都由多次 $\mathbb{F}_{p}$ 乘法/平方组成，底层一次乘法的改进会被整个标量乘法放大。

删除汇编还有安全工程收益：

- 避免 early-clobber、clobber 列表等内联汇编契约错误；
- 减少不同编译器和平台组合的测试矩阵；
- 让普通 C 的边界证明、sanitizer 和审查工具覆盖更多代码；
- 避免手写代码几年后落后，却因维护成本无法及时更新。

项目当时仍保留更快的标量汇编，说明决策是基于具体基准，而不是"一律 C"或"一律汇编"。正确原则是：在目标工具链上测量，并把维护和审计成本计入优化收益。

## 6. 安全修复与性能优化的共同逻辑

上述案例看似分散，实际围绕同一组原则：

| 原则 | 安全体现 | 性能体现 |
|------|----------|----------|
| 语义必须绑定 | `msghash32` 必须由验证者计算 | 明确公开/秘密数据后才能安全选 variable-time |
| 代数等价变换 | lower-S、常数时间掩码保持结果 | Jacobian 比较避免求逆、GLV 分解缩短标量 |
| 实现环境属于算法一部分 | 编译器可重引入分支，汇编约束可破坏正确性 | 编译器生成的 C 可超过旧手写汇编 |
| 预计算需要安全索引 | 秘密索引必须通过 cmov 全表选择 | multi-comb 用表大小换在线加法/倍点 |
| 简单性具有工程价值 | 更少汇编和分支更易审计 | 更简单算法也可能减少指令与代码体积 |

尤其值得注意的是"variable-time 并非天然不安全"。若所有输入都是公开数据，例如 ECDSA 验证中的 $s,r,e,P$，提前终止和数据相关分支不会泄露私钥，反而能提高吞吐量。真正错误的是让秘密数据进入 variable-time 路径，或无法证明某个值已公开。

## 7. 本机实验与结果

### 7.1 构建配置

本报告在 Windows x86_64 上使用：

- CMake 3.27.2；
- MinGW-w64 GCC 13.2.0；
- Release / `-O2`；
- ECDH、extrakeys、Schnorr、MuSig2、ElligatorSwift 全部启用；
- 测试、no-VERIFY 测试、exhaustive tests、示例和 benchmark 全部构建；
- `ECMULT_WINDOW_SIZE=15`；
- 86 KiB `ecmult_gen` 表；
- x86_64 标量汇编可用。

### 7.2 功能验证

运行命令：

    ctest --test-dir build-assignment2 --output-on-failure

结果为 **212/212 通过，0 失败**，总耗时约 100.84 秒。覆盖内容包括：

- ECDSA 签名/验证、边界情况与 Wycheproof 向量；
- ECDH API、坏标量与 Wycheproof 向量；
- BIP 340/Schnorr、Taproot 测试；
- MuSig2 nonce、聚合与规范向量；
- ElligatorSwift 编解码、XDH 与坏标量测试；
- field/scalar/modinv、endomorphism、ecmult；
- 小群 exhaustive tests；
- 普通与 no-VERIFY 两套测试，以及五个示例程序。

验证边界必须如实说明：本 Windows 环境没有 Valgrind，CMake 因而关闭 `ctime_tests`。功能测试通过只能证明已覆盖输入上的结果正确，不能单独证明生成机器码没有侧信道。常数时间的本机强验证应在支持 Valgrind 的 Linux 环境再次运行 `ctime_tests`，并结合目标编译器反汇编。

### 7.3 当前版本基准

设置 `SECP256K1_BENCH_ITERS=20000` 后，本机结果如下：

| 操作 | Min | Avg | Max |
|------|-----|-----|-----|
| ECDSA verify | 28.4 μs | 33.2 μs | 48.3 μs |
| ECDSA sign | 27.8 μs | 29.2 μs | 30.5 μs |
| 公钥生成 | 18.7 μs | 19.9 μs | 21.6 μs |
| ECDH | 41.2 μs | 44.3 μs | 49.3 μs |
| Schnorr sign | 19.6 μs | 19.9 μs | 20.2 μs |
| Schnorr verify | 43.8 μs | 46.9 μs | 52.6 μs |
| ElligatorSwift ECDH | 45.4 μs | 50.0 μs | 58.7 μs |

这些绝对值只描述本机软硬件组合。报告中"12.4%""10%""5%"等相对提升来自对应上游提交在其测试环境中的对照实验，不能用本机单版本结果重复证明。不过，本机结果验证了当前实现可正常构建运行，也展示了签名、验证、密钥协商和模逆的量级。

### 7.4 课件伪造实验

运行：

    python ..\assignment-2\scripts\ecdsa_hash_forgery_demo.py

脚本使用真实 $p,n,G$，实现 affine 点加、标量乘和 ECDSA 验证。它读取一个预先选定且不附带离散对数的有效公钥 $P$，随后只用 $P,u,v$ 构造 $e',r',s'$，输出 `verify(P, e, r, s) = True`。脚本还计算预先选择消息的 SHA-256，结果与 $e'$ 不同。这同时证明了攻击成立和攻击边界：可以伪造"与签名一起选择的哈希"，不能直接伪造预先指定消息。

## 8. 对 Bitcoin 系统的影响分析

### 8.1 不应夸大的内容

- Clang/GCC 常数时间问题主要威胁本地秘密操作，不代表攻击者可从链上公开签名立刻算出私钥。
- RFC 6979 归约修复主要影响任意 32 字节 API 输入和标准一致性，不表示正常 SHA-256 Bitcoin 签名频繁使用错误 nonce。
- ECDH 模块问题不等同于 Bitcoin 交易共识失效；应按使用该模块的具体应用判断。
- 性能优化不会改变曲线、签名方程或共识结果；正确优化必须逐位保持相同数学输出。

### 8.2 真实收益与风险

- **钱包安全：** 签名、nonce、固定基点乘法与常数时间模逆直接关系私钥保密。
- **节点吞吐：** ECDSA/Schnorr 验证和有限域乘法影响初始区块下载、区块验证、mempool 和交易转发成本。
- **P2P 隐私与安全：** ElligatorSwift XDH 支撑 BIP 324 会话密钥协商，秘密标量路径的侧信道性质仍重要。
- **生态互操作：** RFC 6979、BIP 340、BIP 324、BIP 327 测试向量和规范一致性降低跨实现差异。

## 9. 开发与使用建议

1.  **验证者必须拥有消息构造权。** 不要设计"客户端提交 hash + 签名 + 公钥"的鉴权协议；验证端应从规范化业务对象自行计算带域分离的摘要。
2.  **Bitcoin 交易签名必须使用准确 sighash 实现。** 金额、脚本、输入索引和 sighash 类型的绑定错误，与完全不哈希一样可能破坏授权语义。
3.  **升级经过签名的正式版本。** 特别是使用 Clang ≥14、GCC ≥13 或 ECDH 时，不应停留在 v0.3.1/v0.3.2 修复之前的版本。
4.  **秘密路径只使用常数时间 API。** 不要因 `*_var` 更快而把私钥、nonce 或共享秘密计算传入 variable-time 函数。
5.  **把编译器版本纳入密码发布流程。** 升级编译器后重新运行 ctime 测试、sanitizer、测试向量、exhaustive tests 和基准。
6.  **避免秘密数组索引。** 即使访问同一缓存行，细粒度缓存和推测执行也可能泄漏；全表 cmov 的代价是有意支付的安全成本。
7.  **基准必须与目标机器一致。** 预计算表大小、C/汇编选择、编译器和 CPU 微架构都会改变最优配置。
8.  **优先可审计优化。** 能用短小代数推导替代复杂汇编或特殊分支时，应同时评估速度、代码体积和审计成本。

## 10. 结论

本报告从课件中的 ECDSA 伪造公式出发，证明了一个容易被误解但非常重要的事实：签名算法验证的是"公钥、摘要、签名"三元关系；若摘要本身由攻击者提供，攻击者可以反向构造一个满足方程的三元组。安全协议必须把摘要绑定到验证者认可的真实消息。`libsecp256k1` 通过把 `msg32` 明确改名为 `msghash32` 并加入直接警告来降低这一误用风险。

仓库历史进一步说明，密码库的安全边界延伸到规范细节、编译器和汇编约束。RFC 6979 的一次模 $n$ 归约、`volatile` 对编译器重写的阻挡、一个 `&` early-clobber 约束，都可能决定实现是否符合规范、是否常数时间、是否产生正确机器码。

性能优化也不是简单"少执行几条语句"。Jacobian 坐标比较用乘法替代求逆；safegcd 用批量 divsteps 解决模逆；GLV 把 256 位标量拆成两个约 128 位标量；signed-digit multi-comb 把固定基点乘法重排成可预计算的固定加法；现代编译器生成的 C 最终超过旧手写汇编。每项提升都有明确的代数不变量，并通过测试、基准和审查确保优化前后输出一致。

因此，`libsecp256k1` 对网络安全课程最有价值的启示是：高保证密码工程必须同时回答四个问题------算的公式对不对、绑定的消息对不对、机器码是否泄密、实现是否足够快且可审计。只满足其中一项，不能称为完整安全实现。

## 参考资料

1.  Bitcoin Core, [`bitcoin-core/secp256k1`](https://github.com/bitcoin-core/secp256k1), README、CHANGELOG 与当前源代码。
2.  Jonas Nick, [Rename msg32 to msghash32 in ecdsa_sign/verify and add explanation](https://github.com/bitcoin-core/secp256k1/commit/f587f04e35719883546afd54cb491ead18eb6fc7), 2020.
3.  Paul Miller, [Modulo-reduce msg32 inside RFC6979 nonce fn to match spec](https://github.com/bitcoin-core/secp256k1/commit/45f37b650635e46865104f37baed26ef8d2cfb97), 2022.
4.  Tim Ruffing, [Use volatile trick in all fe/scalar cmov implementations](https://github.com/bitcoin-core/secp256k1/commit/4a496a36fb07d6cc8c99e591994f4ce0c3b1174c), 2023.
5.  Pieter Wuille, [Bugfix: mark outputs as early clobber in scalar x86_64 asm](https://github.com/bitcoin-core/secp256k1/commit/0c729ba70d963f2798184b0b8524d7de2f3ced9f), 2023.
6.  D. J. Bernstein and B.-Y. Yang, [Fast constant-time gcd computation and modular inversion](https://gcd.cr.yp.to/papers.html#safegcd), 2019.
7.  Bitcoin Core, [Safegcd inverses, drop Jacobi symbols, remove libgmp](https://github.com/bitcoin-core/secp256k1/commit/26de4dfeb1f1436dae1fcf17f57bdaa43540f940), 2021.
8.  Mike Hamburg, [Fast and compact elliptic-curve cryptography](https://eprint.iacr.org/2012/309), 2012.
9.  Bitcoin Core, [Signed-digit based ecmult_const algorithm](https://github.com/bitcoin-core/secp256k1/commit/40f50d0fbd3c7ee78b4055bc6ca81027025c4148), 2023.
10. Bitcoin Core, [Signed-digit multi-comb ecmult_gen algorithm](https://github.com/bitcoin-core/secp256k1/commit/da515074e3ebc8abc85a4fff3a31d7694ecf897b), 2024.
11. Tim Ruffing, [field: Remove x86_64 asm](https://github.com/bitcoin-core/secp256k1/commit/2f0762fa8fd30b457bc5dcf53403123212091df5), 2023.
12. T. Pornin, [RFC 6979: Deterministic Usage of DSA and ECDSA](https://www.rfc-editor.org/rfc/rfc6979), 2013.
13. Bitcoin Improvement Proposals: [BIP 340](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki), [BIP 341](https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki), [BIP 324](https://github.com/bitcoin/bips/blob/master/bip-0324.mediawiki), [BIP 327](https://github.com/bitcoin/bips/blob/master/bip-0327.mediawiki).

## 附录 A：复现命令

    # 位于 secp256k1 仓库根目录
    cmake -S . -B build-assignment2 -G "MinGW Makefiles" `
      -DCMAKE_BUILD_TYPE=Release `
      -DSECP256K1_BUILD_TESTS=ON `
      -DSECP256K1_BUILD_EXHAUSTIVE_TESTS=ON `
      -DSECP256K1_BUILD_BENCHMARK=ON `
      -DSECP256K1_BUILD_EXAMPLES=ON

    cmake --build build-assignment2 -j 4
    ctest --test-dir build-assignment2 --output-on-failure

    python ..\assignment-2\scripts\ecdsa_hash_forgery_demo.py
    python ..\assignment-2\scripts\rfc6979_reduction_demo.py

    $env:SECP256K1_BENCH_ITERS='20000'
    .\build-assignment2\bin\bench.exe `
      ecdsa_sign ecdsa_verify ec_keygen ecdh schnorrsig_sign schnorrsig_verify
    .\build-assignment2\bin\bench_internal.exe scalar inverse
    .\build-assignment2\bin\bench_internal.exe field inverse

## 附录 B：提交索引

| 类型 | 提交/合并 | 主题 | 上游公开效果 |
|------|-----------|------|-------------|
| 安全接口 | `f587f04e` | 明确 `msghash32`，警告选定哈希伪造 | 防止 API 语义误用 |
| 规范修复 | `45f37b65` | RFC 6979 输入模 $n$ 归约 | 与标准一致 |
| 侧信道 | `4a496a36` | Clang 15 cmov 重新分支 | 恢复秘密路径常数时间意图 |
| 侧信道 | `5fb336f9`, `17fa2173` | GCC 13/ECDH 等条件路径 | v0.3.2 安全修复 |
| 正确性 | `0c729ba7` | scalar asm early-clobber | 防潜在错误汇编/越界读取 |
| 性能 | `ce7eb6fb` | 验证避免有限域求逆 | 降低验证成本 |
| 性能/安全 | `26de4dfe` | safegcd 模逆 | 快速 constant/variable-time 双路径 |
| 性能 | `a1102b12` | ECDH skew 修正 | 约 5% |
| 性能 | `40f50d0f` | signed-digit `ecmult_const` | 约 2% |
| 性能 | `da515074` | signed-digit multi-comb `ecmult_gen` | GCC 约 12.4%，Clang 约 11.5% |
| 性能/维护 | `2f0762fa` | 删除旧 field asm | `fe_mul` >20%，验证 >10% |
