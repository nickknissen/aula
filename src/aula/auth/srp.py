"""Custom SRP (Secure Remote Password) implementation for MitID authentication."""

import hashlib
import secrets

from Crypto.Cipher import AES

from ._utils import bytes_to_hex, hex_to_int, int_to_bytes

# MitID SRP parameters: 2048-bit safe prime and generator
_N = (  # noqa: E501
    4983313092069490398852700692508795473567251422586244806694940877242664573189903192937797446992068818099986958054998012331720869136296780936009508700487789962429161515853541556719593346959929531150706457338429058926505817847524855862259333438239756474464759974189984231409170758360686392625635632084395639143229889862041528635906990913087245817959460948345336333086784608823084788906689865566621015175424691535711520273786261989851360868669067101108956159530739641990220546209432953829448997561743719584980402874346226230488627145977608389858706391858138200618631385210304429902847702141587470513336905449351327122086464725143970313054358650488241167131544692349123381333204515637608656643608393788598011108539679620836313915590459891513992208387515629240292926570894321165482608544030173975452781623791805196546326996790536207359143527182077625412731080411108775183565594553871817639221414953634530830290393130518228654795859
)
_G = 2


def _sha256(data: bytes) -> bytes:
    """Compute SHA-256 digest."""
    return hashlib.sha256(data).digest()


def _sha256_hex(data: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def _pad_to_n_length(value: bytes) -> bytes:
    """Pad bytes with leading zeros to match the byte length of N."""
    n_length = len(int_to_bytes(_N))
    return value.zfill(n_length)


class CustomSRP:
    """SRP client for MitID's non-standard SRP variant.

    Implements the three-stage SRP handshake (init, prove, verify)
    plus AES-GCM authenticated encryption using the derived session key.
    """

    def __init__(self) -> None:
        self._private_key: int = 0
        self._public_key: int = 0
        self._server_public_key: int = 0
        self._hashed_password: int = 0
        self._session_key_bytes: bytes = b""
        self._m1_hex: str = ""

    # -- Public API (the three SRP stages + encryption) --

    def srp_stage1(self) -> str:
        """Stage 1: Generate client key pair and return public key A as hex."""
        self._private_key = secrets.randbits(256)
        self._public_key = pow(_G, self._private_key, _N)
        return format(self._public_key, "x")

    def srp_stage3(self, srp_salt: str, random_b: str, password: str, auth_session_id: str) -> str:
        """Stage 3: Compute session key and client proof M1.

        Args:
            srp_salt: Salt provided by the server.
            random_b: Server's public value B as hex.
            password: Derived password (pre-hashed by caller).
            auth_session_id: The authenticator session ID.

        Returns:
            The M1 proof as a hex string.
        """
        self._server_public_key = hex_to_int(random_b)

        if self._server_public_key == 0 or self._server_public_key % _N == 0:
            raise ValueError("Server public key B did not pass safety check")

        self._hashed_password = hex_to_int(_sha256_hex((srp_salt + password).encode("ascii")))

        raw_session_key = self._compute_session_key()
        self._session_key_bytes = _sha256(str(raw_session_key).encode("utf-8"))

        identity_hash = _sha256_hex(auth_session_id.encode("utf-8"))
        self._m1_hex = self._compute_m1(identity_hash, srp_salt)

        return self._m1_hex

    def srp_stage5(self, m2_hex: str) -> bool:
        """Stage 5: Verify server proof M2.

        Returns:
            True if the server's proof is valid.
        """
        m1_int = int(self._m1_hex, 16)
        expected = _sha256_hex(
            (str(self._public_key) + str(m1_int) + bytes_to_hex(self._session_key_bytes)).encode(
                "utf-8"
            )
        )
        return expected == m2_hex

    def auth_enc(self, plain_text: bytes) -> bytes:
        """Encrypt data with AES-256-GCM using the derived session key.

        Returns:
            IV + ciphertext + GCM tag.
        """
        iv = secrets.token_bytes(16)
        cipher = AES.new(self._session_key_bytes, AES.MODE_GCM, iv)
        ciphertext, tag = cipher.encrypt_and_digest(plain_text)
        return iv + ciphertext + tag

    @property
    def session_key_bytes(self) -> bytes:
        """The derived session key (available after srp_stage3)."""
        return self._session_key_bytes

    # -- Internal computations --

    def _compute_little_s(self) -> int:
        """Compute SRP multiplier k = H(N, g)."""
        n_bytes = int_to_bytes(_N)
        g_bytes = int_to_bytes(_G).rjust(len(n_bytes), b"\0")

        return hex_to_int(_sha256_hex(str(_N).encode("utf-8") + g_bytes))

    def _compute_u(self) -> int:
        """Compute scrambling parameter u = H(A, B)."""
        a_bytes = _pad_to_n_length(int_to_bytes(self._public_key))
        b_bytes = _pad_to_n_length(int_to_bytes(self._server_public_key))

        return hex_to_int(_sha256_hex(a_bytes + b_bytes)) % _N

    def _compute_session_key(self) -> int:
        u = self._compute_u()
        s = self._compute_little_s()

        exponent = u * self._hashed_password + self._private_key
        base = self._server_public_key - pow(_G, self._hashed_password, _N) * s
        return pow(base, exponent, _N)

    def _compute_m1(self, identity_hash: str, srp_salt: str) -> str:
        n_hash = hex_to_int(_sha256_hex(str(_N).encode("utf-8")))
        g_hash = hex_to_int(_sha256_hex(str(_G).encode("utf-8")))
        xor_hash = n_hash ^ g_hash

        payload = (
            str(xor_hash)
            + identity_hash
            + srp_salt
            + str(self._public_key)
            + str(self._server_public_key)
            + bytes_to_hex(self._session_key_bytes)
        )
        return _sha256_hex(payload.encode("ascii"))
