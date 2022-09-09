import copy
import math

import pennylane as qml
import numpy as np
import jax
import jax.numpy as jnp
from sklearn.svm import SVR
from sklearn.metrics import mean_squared_error
from scipy.stats import unitary_group


class ScrambledKernel:

    def __init__(self, X_train, y_train, X_validation, y_validation):
        self.X_train = X_train
        self.y_train = y_train
        self.training_gram = None
        self.X_validation = X_validation
        self.y_validation = y_validation
        self.validation_gram = None
        self.n_qubits = X_train.shape[1]
        self.state = jnp.array(np.random.normal(size=((4**self.n_qubits)-1,)))
        self.scrambled_kernel = self.create_pennylane_function()
        self.repetitions = math.ceil((4**self.n_qubits - 1) / self.n_qubits)

    def encode_x_in_random_parameters(self, x):
        repeated_x = jnp.tile(x, self.repetitions)[:(4**self.n_qubits)-1]
        return jnp.multiply(self.state, repeated_x)  # pointwise multiplication

    def create_pennylane_function(self):
        # define function to compile
        def trainable_kernel_wrapper(x1, x2, weights, bandwidth):
            device = qml.device("default.qubit.jax", wires=self.n_qubits)

            # create projector (measures probability of having all "00...0")
            projector = np.zeros((2 ** self.n_qubits, 2 ** self.n_qubits))
            projector[0, 0] = 1

            # define the circuit for the quantum kernel ("overlap test" circuit)
            @qml.qnode(device, interface='jax')
            def random_kernel():
                qml.ArbitraryUnitary(
                                self.encode_x_in_random_parameters(x1),
                                wires=range(self.n_qubits))
                qml.adjoint(qml.ArbitraryUnitary)(
                                 self.encode_x_in_random_parameters(x2),
                                 wires=range(self.n_qubits))
                return qml.expval(qml.Hermitian(projector, wires=range(self.n_qubits)))

            return random_kernel()

        return jax.jit(trainable_kernel_wrapper)

    def estimate_mse(self, weights=None, X_test=None, y_test=None):
        X_test = self.X_validation if X_test is None else X_test
        y_test = self.y_validation if y_test is None else y_test
        training_gram = self.get_kernel_values(self.X_train, weights=weights)
        testing_gram = self.get_kernel_values(X_test, self.X_train, weights=weights)
        return self.estimate_mse_svr(training_gram, self.y_train, testing_gram, y_test)

    def estimate_mse_svr(self, gram_train, y_train, gram_test, y_test):
        svr = SVR()
        svr.fit(gram_train, y_train.ravel())
        y_pred = svr.predict(gram_test)
        return mean_squared_error(y_test.ravel(), y_pred.ravel())

    def get_kernel_values(self, X1, X2=None, weights=None, bandwidth=None):
        weights = self.state if weights is None else weights
        bandwidth = 1.0 if bandwidth is None else bandwidth
        if X2 is None:
            m = self.X_train.shape[0]
            kernel_gram = np.eye(m)
            for i in range(m):
                for j in range(i + 1, m):
                    value = self.scrambled_kernel(X1[i], X1[j], weights, bandwidth)
                    kernel_gram[i][j] = value
                    kernel_gram[j][i] = value
                    print(".", end="")
        else:
            kernel_gram = np.zeros(shape=(len(X1), len(X2)))
            for i in range(len(X1)):
                for j in range(len(X2)):
                    kernel_gram[i][j] = self.scrambled_kernel(X1[i], X2[j], weights, bandwidth)
                    print(".", end="")
        return kernel_gram
