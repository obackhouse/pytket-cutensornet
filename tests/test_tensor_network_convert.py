from typing import List, Union
import warnings
import random
import cmath
import numpy as np
from numpy.typing import NDArray
import pytest
from pytket.circuit import ToffoliBox, Qubit  # type: ignore
from pytket.passes import DecomposeBoxes, CnXPairwiseDecomposition  # type: ignore
from pytket.transform import Transform  # type: ignore

try:
    import cuquantum as cq  # type: ignore
except ImportError:
    warnings.warn("local settings failed to import cutensornet", ImportWarning)
from pytket.circuit import Circuit

from pytket.extensions.cutensornet.tensor_network_convert import (  # type: ignore
    tk_to_tensor_network,
    TensorNetwork,
)


def state_contract(tn: List[Union[NDArray, List]], nqubit: int) -> NDArray:
    """Calls cuQuantum contract function to contract an input state tensor network."""
    state_tn = tn.copy()
    state: NDArray = cq.contract(*state_tn).flatten()
    return state


def circuit_overlap_contract(circuit_ket: Circuit) -> float:
    """Calculates an overlap of a state circuit with its adjoint."""
    ket_net = TensorNetwork(circuit_ket)
    overlap_net_interleaved = ket_net.vdot(TensorNetwork(circuit_ket))
    overlap: float = cq.contract(*overlap_net_interleaved)
    return overlap


@pytest.mark.parametrize(
    "circuit",
    [
        pytest.lazy_fixture("q2_x0"),  # type: ignore
        pytest.lazy_fixture("q2_x1"),  # type: ignore
        pytest.lazy_fixture("q2_v0"),  # type: ignore
        pytest.lazy_fixture("q2_x0cx01"),  # type: ignore
        pytest.lazy_fixture("q2_x1cx10x1"),  # type: ignore
        pytest.lazy_fixture("q2_x0cx01cx10"),  # type: ignore
        pytest.lazy_fixture("q2_v0cx01cx10"),  # type: ignore
        pytest.lazy_fixture("q2_hadamard_test"),  # type: ignore
        pytest.lazy_fixture("q2_lcu1"),  # type: ignore
        pytest.lazy_fixture("q2_lcu2"),  # type: ignore
        pytest.lazy_fixture("q2_lcu3"),  # type: ignore
        pytest.lazy_fixture("q3_v0cx02"),  # type: ignore
        pytest.lazy_fixture("q3_cx01cz12x1rx0"),  # type: ignore
        pytest.lazy_fixture("q4_lcu1"),  # type: ignore
        pytest.lazy_fixture("q4_multicontrols"),  # type: ignore
        pytest.lazy_fixture("q4_with_creates"),  # type: ignore
    ],
)
def test_convert_statevec_overlap(circuit: Circuit) -> None:
    tn = tk_to_tensor_network(circuit)
    result_cu = state_contract(tn, circuit.n_qubits).flatten().round(10)
    state_vector = np.array([circuit.get_statevector()])
    assert np.allclose(result_cu, state_vector)
    ovl = circuit_overlap_contract(circuit)
    assert ovl == pytest.approx(1.0)


def test_toffoli_box_with_implicit_swaps() -> None:
    # Using specific permutation here
    perm = {
        (False, False): (True, True),
        (False, True): (False, False),
        (True, False): (True, False),
        (True, True): (False, True),
    }

    # Create a circuit with more qubits and multiple applications of the permutation
    # above
    ket_circ = Circuit(3)

    # Create the circuit
    ket_circ.add_toffolibox(ToffoliBox(perm), [Qubit(0), Qubit(1)])  # type: ignore
    ket_circ.add_toffolibox(ToffoliBox(perm), [Qubit(1), Qubit(2)])  # type: ignore

    DecomposeBoxes().apply(ket_circ)
    CnXPairwiseDecomposition().apply(ket_circ)
    Transform.OptimiseCliffords().apply(ket_circ)

    # Convert and contract
    ket_net = TensorNetwork(ket_circ)
    ket_net_vector = cq.contract(*ket_net.cuquantum_interleaved).flatten()
    ket_net_vector = ket_net_vector * cmath.exp(1j * cmath.pi * ket_circ.phase)

    # Compare to pytket statevector
    ket_pytket_vector = ket_circ.get_statevector()

    assert np.allclose(ket_net_vector, ket_pytket_vector)


@pytest.mark.parametrize("n_qubits", [4, 5, 6])
def test_generalised_toffoli_box(n_qubits: int) -> None:
    def to_bool_tuple(n_qubits: int, x: int) -> tuple:
        bool_list = []
        for i in reversed(range(n_qubits)):
            bool_list.append((x >> i) % 2 == 1)
        return tuple(bool_list)

    random.seed(1)

    # Generate a random permutation
    cycle = list(range(2**n_qubits))
    random.shuffle(cycle)

    perm = dict()
    for orig, dest in enumerate(cycle):
        perm[to_bool_tuple(n_qubits, orig)] = to_bool_tuple(n_qubits, dest)

    # Create a circuit implementing the permutation above
    ket_circ = ToffoliBox(perm).get_circuit()  # type: ignore

    DecomposeBoxes().apply(ket_circ)
    CnXPairwiseDecomposition().apply(ket_circ)
    Transform.OptimiseCliffords().apply(ket_circ)

    # The ideal outcome on ket 0 input
    output = perm[(False,) * n_qubits]
    # A trivial circuit generating this state
    bra_circ = Circuit()
    for q in ket_circ.qubits:
        bra_circ.add_qubit(q)
    for i, bit in enumerate(output):
        if bit:
            bra_circ.X(i)

    ket_net = TensorNetwork(ket_circ)
    ket_net_vector = cq.contract(*ket_net.cuquantum_interleaved).flatten()
    ket_net_vector = ket_net_vector * cmath.exp(1j * cmath.pi * ket_circ.phase)
    ket_pytket_vector = ket_circ.get_statevector()
    assert np.allclose(ket_net_vector, ket_pytket_vector)

    bra_net = TensorNetwork(bra_circ)
    bra_net_vector = cq.contract(*bra_net.cuquantum_interleaved).flatten()
    bra_net_vector = bra_net_vector * cmath.exp(1j * cmath.pi * bra_circ.phase)
    bra_pytket_vector = bra_circ.get_statevector()
    assert np.allclose(bra_net_vector, bra_pytket_vector)

    np.isclose(abs(cq.contract(*ket_net.vdot(bra_net))), 1.0)
