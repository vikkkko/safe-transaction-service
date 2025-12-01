from typing import Any
from urllib.parse import urlparse

from django import forms
from django.core import exceptions
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from eth_abi import encode as encode_abi
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth import EthereumClient
from safe_eth.util.util import to_0x_hex_str
from web3 import Web3
from web3.types import LogReceipt


class HexField(forms.CharField):
    # TODO Move this to safe-eth-py
    default_error_messages = {
        "invalid": _("Enter a valid hexadecimal."),
    }

    def to_python(self, value: str | bytes | memoryview) -> HexBytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, memoryview):
            return HexBytes(bytes(value))
        if value in self.empty_values:
            return None

        value = str(value)
        if self.strip:
            try:
                value = HexBytes(value.strip())
            except (TypeError, ValueError) as exc:
                raise exceptions.ValidationError(
                    self.error_messages["invalid"],
                    code="invalid",
                ) from exc
        return value

    def prepare_value(self, value: memoryview) -> str:
        return to_0x_hex_str(bytes(value)) if value else ""


def clean_receipt_log(receipt_log: LogReceipt) -> dict[str, Any] | None:
    """
    Clean receipt log and make them JSON compliant

    :param receipt_log:
    :return:
    """

    parsed_log = {
        "address": receipt_log["address"],
        "data": to_0x_hex_str(receipt_log["data"]),
        "topics": [to_0x_hex_str(topic) for topic in receipt_log["topics"]],
    }
    return parsed_log


def validate_url(url: str) -> None:
    result = urlparse(url)
    if not all(
        (
            result.scheme
            in (
                "http",
                "https",
            ),
            result.netloc,
        )
    ):
        raise ValidationError(f"{url} is not a valid url")


# Multichannel nonce support
SAFE_TX_TYPEHASH_V1_4_1 = Web3.keccak(
    text=(
        "SafeTx(address to,uint256 value,bytes data,uint8 operation,"
        "uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,"
        "address gasToken,address refundReceiver,uint256 nonce)"
    )
)

SAFE_TX_TYPEHASH_MULTICHANNEL = Web3.keccak(
    text=(
        "SafeTx(uint256 channel,address to,uint256 value,bytes data,"
        "uint8 operation,uint256 safeTxGas,uint256 baseGas,"
        "uint256 gasPrice,address gasToken,address refundReceiver,"
        "uint256 nonce)"
    )
)


def get_safe_version(
    ethereum_client: EthereumClient, safe_address: ChecksumAddress
) -> str | None:
    """
    Get Safe contract version by calling VERSION() function

    :param ethereum_client: Ethereum client instance
    :param safe_address: Safe contract address
    :return: Version string or None if not available
    """
    try:
        # ABI for VERSION() function
        version_abi = [
            {
                "constant": True,
                "inputs": [],
                "name": "VERSION",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function",
            }
        ]
        contract = ethereum_client.w3.eth.contract(
            address=safe_address, abi=version_abi
        )
        version = contract.functions.VERSION().call()
        return version
    except Exception:
        return None


def supports_multichannel(version: str | None) -> bool:
    """
    Check if Safe version supports multichannel nonce

    :param version: Safe version string
    :return: True if multichannel is supported
    """
    if not version:
        return False
    # Support both old format (1.5.0-multichannel.1) and new format (1.5.0+multichannel1)
    return "multichannel" in version.lower()


def calculate_safe_tx_hash_multichannel(
    ethereum_client: EthereumClient,
    safe_address: ChecksumAddress,
    channel: int,
    to: ChecksumAddress,
    value: int,
    data: bytes,
    operation: int,
    safe_tx_gas: int,
    base_gas: int,
    gas_price: int,
    gas_token: ChecksumAddress,
    refund_receiver: ChecksumAddress,
    nonce: int,
) -> bytes:
    """
    Calculate Safe transaction hash for multichannel version

    :param ethereum_client: Ethereum client instance
    :param safe_address: Safe contract address
    :param channel: Channel number
    :param to: Destination address
    :param value: Ether value
    :param data: Transaction data
    :param operation: Operation type (0=Call, 1=DelegateCall)
    :param safe_tx_gas: Gas for Safe transaction
    :param base_gas: Base gas
    :param gas_price: Gas price
    :param gas_token: Token address for gas payment
    :param refund_receiver: Address to receive refund
    :param nonce: Transaction nonce
    :return: Safe transaction hash (bytes32)
    """
    # Encode the transaction data with channel as first parameter
    data_hash = Web3.keccak(
        encode_abi(
            [
                "bytes32",
                "uint256",
                "address",
                "uint256",
                "bytes32",
                "uint8",
                "uint256",
                "uint256",
                "uint256",
                "address",
                "address",
                "uint256",
            ],
            [
                SAFE_TX_TYPEHASH_MULTICHANNEL,
                channel,
                to,
                value,
                Web3.keccak(data) if data else Web3.keccak(b""),
                operation,
                safe_tx_gas,
                base_gas,
                gas_price,
                gas_token,
                refund_receiver,
                nonce,
            ],
        )
    )

    # Get domain separator
    domain_separator = get_domain_separator(ethereum_client, safe_address)

    # Return EIP-712 hash
    return Web3.keccak(b"\x19\x01" + domain_separator + data_hash)


def get_domain_separator(
    ethereum_client: EthereumClient, safe_address: ChecksumAddress
) -> bytes:
    """
    Get EIP-712 domain separator for Safe

    :param ethereum_client: Ethereum client instance
    :param safe_address: Safe contract address
    :return: Domain separator (bytes32)
    """
    # EIP-712 Domain separator
    # keccak256("EIP712Domain(uint256 chainId,address verifyingContract)")
    domain_separator_typehash = Web3.keccak(
        text="EIP712Domain(uint256 chainId,address verifyingContract)"
    )

    # Get chain ID from ethereum client
    chain_id = ethereum_client.get_chain_id()

    return Web3.keccak(
        encode_abi(
            ["bytes32", "uint256", "address"],
            [domain_separator_typehash, chain_id, safe_address],
        )
    )


def get_channel_nonce(
    ethereum_client: EthereumClient,
    safe_address: ChecksumAddress,
    channel: int,
) -> int:
    """
    Get nonce for a specific channel from Safe contract

    :param ethereum_client: Ethereum client instance
    :param safe_address: Safe contract address
    :param channel: Channel number
    :return: Current nonce for the channel
    """
    try:
        # ABI for channelNonces(uint256) function
        channel_nonces_abi = [
            {
                "constant": True,
                "inputs": [{"name": "channel", "type": "uint256"}],
                "name": "channelNonces",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function",
            }
        ]
        contract = ethereum_client.w3.eth.contract(
            address=safe_address, abi=channel_nonces_abi
        )
        nonce = contract.functions.channelNonces(channel).call()
        return nonce
    except Exception:
        # If channelNonces doesn't exist, this is not a multichannel Safe
        # Fall back to standard nonce() for channel 0
        if channel == 0:
            nonce_abi = [
                {
                    "constant": True,
                    "inputs": [],
                    "name": "nonce",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function",
                }
            ]
            contract = ethereum_client.w3.eth.contract(
                address=safe_address, abi=nonce_abi
            )
            return contract.functions.nonce().call()
        return 0
