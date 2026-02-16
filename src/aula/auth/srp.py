"""Custom SRP (Secure Remote Password) implementation for MitID authentication."""

import hashlib
import secrets

from Crypto.Cipher import AES

from ._utils import bytes_to_hex, hex_to_int, int_to_bytes


class CustomSRP:
    def SRPStage1(self) -> str:
        self.N = (  # noqa: E501
            4983313092069490398852700692508795473567251422586244806694940877242664573189903192937797446992068818099986958054998012331720869136296780936009508700487789962429161515853541556719593346959929531150706457338429058926505817847524855862259333438239756474464759974189984231409170758360686392625635632084395639143229889862041528635906990913087245817959460948345336333086784608823084788906689865566621015175424691535711520273786261989851360868669067101108956159530739641990220546209432953829448997561743719584980402874346226230488627145977608389858706391858138200618631385210304429902847702141587470513336905449351327122086464725143970313054358650488241167131544692349123381333204515637608656643608393788598011108539679620836313915590459891513992208387515629240292926570894321165482608544030173975452781623791805196546326996790536207359143527182077625412731080411108775183565594553871817639221414953634530830290393130518228654795859
        )
        self.g = 2
        self.a = secrets.randbits(256)

        self.A = pow(self.g, self.a, self.N)
        return format(self.A, "x")

    def computeLittleS(self) -> int:
        N_bytes = int_to_bytes(self.N)
        g_bytes = int_to_bytes(self.g)

        # Prepend g_bytes with |N_bytes|-|g_bytes| of 0
        g_bytes = (b"\0" * (len(N_bytes) - len(g_bytes))) + g_bytes

        m = hashlib.sha256()
        m.update(str(self.N).encode("utf-8") + g_bytes)
        return hex_to_int(m.hexdigest())

    def computeU(self) -> int:
        N_length = len(int_to_bytes(self.N))
        A_bytes = int_to_bytes(self.A)
        B_bytes = int_to_bytes(self.B)

        # Prepend A_bytes with |N_bytes|-|A_bytes| of 0
        A_bytes = (b"\0" * (N_length - len(A_bytes))) + A_bytes

        # Prepend B_bytes with |N_bytes|-|B_bytes| of 0
        B_bytes = (b"\0" * (N_length - len(B_bytes))) + B_bytes

        m = hashlib.sha256()
        m.update(A_bytes + B_bytes)
        return hex_to_int(m.hexdigest()) % self.N

    def computeSessionKey(self) -> int:
        u = self.computeU()
        s = self.computeLittleS()

        a = u * self.hashed_password + self.a
        c = pow((self.B - (pow(self.g, self.hashed_password, self.N) * s)), a, self.N)
        if a < 0:
            a += self.N

        return c

    def computeM1(self, r: str, srpSalt: str) -> str:
        m = hashlib.sha256()
        m.update(str(self.N).encode("utf-8"))
        N = hex_to_int(m.hexdigest())

        m = hashlib.sha256()
        m.update(str(self.g).encode("utf-8"))
        g = hex_to_int(m.hexdigest())
        a = N ^ g

        m = hashlib.sha256()
        m.update(
            (str(a) + r + srpSalt + str(self.A) + str(self.B) + bytes_to_hex(self.K_bits)).encode(
                "ascii"
            )
        )
        return m.hexdigest()

    def SRPStage3(self, srpSalt: str, randomB: str, password: str, auth_session_id: str) -> str:
        self.B = hex_to_int(randomB)

        if self.B == 0 or self.B % self.N == 0:
            raise ValueError("randomB did not pass safety check")

        m = hashlib.sha256()
        m.update((srpSalt + password).encode("ascii"))
        self.hashed_password = hex_to_int(m.hexdigest())

        a = self.computeSessionKey()

        m = hashlib.sha256()
        m.update(str(a).encode("utf-8"))
        self.K_bits = m.digest()

        m = hashlib.sha256()
        m.update(auth_session_id.encode("utf-8"))
        I_hex = m.hexdigest()

        self.M1_hex = self.computeM1(I_hex, srpSalt)

        return self.M1_hex

    # Should satisfy if the server is correct
    # Interestingly enough, this cannot be checked for the pin-binding proof
    def SRPStage5(self, M2_hex: str) -> bool:
        M1_bigInt = int(self.M1_hex, 16)

        m = hashlib.sha256()
        m.update((str(self.A) + str(M1_bigInt) + bytes_to_hex(self.K_bits)).encode("utf-8"))
        M2_hex_verify = m.hexdigest()
        return M2_hex_verify == M2_hex

    def AuthEnc(self, plainText: bytes) -> bytes:
        iv = secrets.token_bytes(16)
        cipher = AES.new(self.K_bits, AES.MODE_GCM, iv)
        ciphertext, tag = cipher.encrypt_and_digest(plainText)
        return iv + ciphertext + tag
