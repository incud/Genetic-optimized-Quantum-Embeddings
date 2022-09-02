from __future__ import division

from copy import deepcopy
from mcts import mcts
from itertools import product
import numpy as np
import pennylane as qml
from .combinatorial_kernel import CombinatorialFeatureMap
from sklearn.svm import SVR
from sklearn.metrics import mean_squared_error
import jax
import jax.numpy as jnp


class CombinatorialKernelMtcs:

    def __init__(self, solution, n_qubits, n_layers, n_operations, X_train, y_train, X_validation, y_validation, time_limit=1000):
        self.solution = solution
        self.n_qubits = n_qubits
        self.n_layers = n_layers
        self.n_operations = n_operations
        self.searcher = mcts(timeLimit=time_limit)
        self.state = CombinatorialKernelMctsState(solution, n_qubits, n_layers, n_operations, X_train, y_train, X_validation, y_validation)

    def search(self):
        return self.searcher.search(initialState=self.state)


class CombinatorialKernelMctsState:

    def __init__(self, solution, n_qubits, n_layers, n_operations, X_train, y_train, X_validation, y_validation):
        self.solution = solution
        self.n_qubits = n_qubits
        self.n_layers = n_layers
        self.n_gates = n_qubits * 2 * n_layers
        self.n_operations = n_operations
        self.energy_calculation_performed = 0
        self.energy_calculation_discarded = 0
        self.X_train = X_train
        self.y_train = y_train
        self.X_validation = X_validation
        self.y_validation = y_validation
        self.combinatorial_kernel = self.create_pennylane_function()

    def getCurrentPlayer(self):
        return self.solution

    def getPossibleActions(self):
        return list(product(list(range(self.n_gates)), [0, 1]))

    def takeAction(self, action):
        print("Take action ", action)
        gate, action_type = action
        newState = deepcopy(self)
        if action_type == 0:
            newState.solution[gate][0] = min(self.solution[gate][0] + 1, 15)
        else:
            newState.solution[gate][1] = min(self.solution[gate][1] + 1, self.n_operations)
        return newState

    def isTerminal(self):
        return False

    def getReward(self):
        print("Calculate reward")
        self.energy_calculation_performed += 1
        print(self.solution.ravel())
        # first use "concentration around mean" criteria
        estimated_variance, _ = self.estimate_variance_of_kernel()
        print(f"Estimated variance: {estimated_variance:0.3f}", end="")
        if estimated_variance < 0.1:
            self.energy_calculation_discarded += 1
            print("")
            return 0.0
        else:
            # then estimate accuracy
            mse = self.estimate_mse()
            print(f"\tMSE: {mse:0.3f}")
            return 1 / mse

    def create_pennylane_function(self):

        def combinatorial_kernel_wrapper(x1, x2, solution, bandwidth):
            device = qml.device("default.qubit.jax", wires=self.n_qubits)

            # create projector (measures probability of having all "00...0")
            projector = np.zeros((2 ** self.n_qubits, 2 ** self.n_qubits))
            projector[0, 0] = 1

            # define the circuit for the quantum kernel ("overlap test" circuit)
            @qml.qnode(device, interface='jax')
            def combinatorial_kernel():
                CombinatorialFeatureMap(x1, self.n_qubits, self.n_layers, solution, bandwidth)
                qml.adjoint(CombinatorialFeatureMap)(x2, self.n_qubits, self.n_layers, solution, bandwidth)
                return qml.expval(qml.Hermitian(projector, wires=range(self.n_qubits)))

            return combinatorial_kernel()

        return jax.jit(combinatorial_kernel_wrapper)

    def estimate_variance_of_kernel(self, n_sample_variance=5):
        kernel_values = []
        for i in range(n_sample_variance):
            indexes = np.random.choice(len(self.X_train), 2)
            x1, x2 = self.X_train[indexes[0]], self.X_train[indexes[1]]
            inner_product = self.combinatorial_kernel(x1, x2, self.solution, 1.0)
            kernel_values.append(inner_product)
        return np.var(kernel_values), kernel_values

    def estimate_mse(self, solution=None, X_test=None, y_test=None):
        X_test = self.X_validation if X_test is None else X_test
        y_test = self.y_validation if y_test is None else y_test
        training_gram = self.get_kernel_values(self.X_train, solution=solution)
        validation_gram = self.get_kernel_values(X_test, self.X_train, solution=solution)
        svr = SVR()
        svr.fit(training_gram, self.y_train.ravel())
        y_pred = svr.predict(validation_gram)
        return mean_squared_error(y_test.ravel(), y_pred.ravel())

    def get_kernel_values(self, X1, X2=None, solution=None, bandwidth=None):
        solution = self.solution if solution is None else solution
        bandwidth = 1.0 if bandwidth is None else bandwidth
        if X2 is None:
            m = self.X_train.shape[0]
            kernel_gram = np.eye(m)
            for i in range(m):
                for j in range(i + 1, m):
                    value = self.combinatorial_kernel(X1[i], X1[j], solution, bandwidth)
                    kernel_gram[i][j] = value
                    kernel_gram[j][i] = value
        else:
            kernel_gram = np.zeros(shape=(len(X1), len(X2)))
            for i in range(len(X1)):
                for j in range(len(X2)):
                    kernel_gram[i][j] = self.combinatorial_kernel(X1[i], X2[j], solution, bandwidth)
        return kernel_gram
