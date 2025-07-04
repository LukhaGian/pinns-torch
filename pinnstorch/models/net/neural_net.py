from typing import Dict, List

import numpy as np
import torch
from torch import nn

class Sin(nn.Module):
    """
    Sine activation function, used in SIREN framework
    """
    def forward(self, input):
        return torch.sin(input)


class FCN(nn.Module):
    """A simple fully-connected neural net for solving equations.

    In this model, lower and upper bound will be used for normalization of input data
    """
    output_names: List[str]
    
    def __init__(self, layers, lb, ub, output_names, act_function: str = "sin", discrete: bool = False) -> None:
        """Initialize a `FCN` module.

        :param layers: The list indicating number of neurons in each layer.
        :param lb: Lower bound for the inputs.
        :param ub: Upper bound for the inputs.
        :param output_names: Names of outputs of net.
        :param act_function: Activation function to use in the FCN layers
        :param discrete: If the problem is discrete or not.
        """
        super().__init__()

        self.model = self.initalize_net(layers, act_function)
        self.register_buffer("lb", torch.tensor(lb, dtype=torch.float32, requires_grad=False))
        self.register_buffer("ub", torch.tensor(ub, dtype=torch.float32, requires_grad=False))
        self.output_names = output_names
        self.discrete = discrete

    def initalize_net(self, layers: List, act_function: str):
        """Initialize the layers of the neural network.

        :param layers: The list indicating number of neurons in each layer.
        :param act_function: Activation function to use in the FCN layers
        :return: The initialized neural network.
        """

        initializer = nn.init.xavier_uniform_
        net = nn.Sequential()

        input_layer = nn.Linear(layers[0], layers[1])
        initializer(input_layer.weight)

        net.add_module("input", input_layer)
        if act_function == "sin":
            net.add_module("activation_1", Sin())
        else:
            net.add_module("activation_1", nn.Tanh())


        for i in range(1, len(layers) - 2):
            hidden_layer = nn.Linear(layers[i], layers[i + 1])
            initializer(hidden_layer.weight)
            net.add_module(f"hidden_{i+1}", hidden_layer)
            if act_function == "sin":
                net.add_module(f"activation_{i+1}", Sin())
            else:
                net.add_module(f"activation_{i+1}", nn.Tanh())


        output_layer = nn.Linear(layers[-2], layers[-1])
        initializer(output_layer.weight)
        net.add_module("output", output_layer)
        return net
    
    def forward(self, spatial: List[torch.Tensor], time: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Perform a single forward pass through the network.

        :param spatial: List of input spatial tensors.
        :param time: Input tensor representing time.
        :return: A tensor of solutions.
        """

        # Discrete Mode
        if self.discrete:
            if len(spatial) == 2:
                x, y = spatial
                z = torch.cat((x, y), 1)
            elif len(spatial) == 3:
                x, y, z = spatial
                z = torch.cat((x, y, z), 1)
            else:
                z = spatial[0]
            z = 2.0 * (z - self.lb[:-1]) / (self.ub[:-1] - self.lb[:-1]) - 1.0

        # Continuous Mode
        else:
            if len(spatial) == 1:
                x = spatial[0]
                z = torch.cat((x, time), 1)
            elif len(spatial) == 2:
                x, y = spatial
                z = torch.cat((x, y, time), 1)
            else:
                x, y, z = spatial
                z = torch.cat((x, y, z, time), 1)
            z = 2.0 * (z - self.lb) / (self.ub - self.lb) - 1.0

        z = self.model(z)

        # Discrete Mode
        if self.discrete:
            outputs_dict = {name: z for i, name in enumerate(self.output_names)}

        # Continuous Mode
        else:
            outputs_dict = {name: z[:, i : i + 1] for i, name in enumerate(self.output_names)}
        return outputs_dict


class NetHFM(nn.Module):
    """A simple fully-connected neural net for solving equations.

    In this model, mean and std will be used for normalization of input data. Also, weight
    normalization will be done.
    """
    output_names: List[str]
    
    def __init__(self, mean, std, layers: List, output_names: List):
        super().__init__()
        """Initialize a `NetHFM` module.

        :param mesh: The number of layers.
        :param layers: The list indicating number of neurons in each layer.
        :param output_names: Names of outputs of net.
        """
        self.num_layers = len(layers)
        self.output_names = output_names

        self.register_buffer("X_mean", torch.from_numpy(mean))
        self.register_buffer("X_std", torch.from_numpy(std))

        self.initalize_net(layers)
        self.sigmoid = nn.Sigmoid()

    def initalize_net(self, layers: List) -> None:
        """Initialize the neural network weights, biases, and gammas.

        :param layers: The list indicating number of neurons in each layer.
        """

        self.weights = []
        self.biases = []
        self.gammas = []

        for i in range(0, self.num_layers - 1):
            in_dim = layers[i]
            out_dim = layers[i + 1]
            W = np.random.normal(size=[in_dim, out_dim])
            b = np.zeros([1, out_dim])
            g = np.ones([1, out_dim])
            # tensorflow variables
            self.weights.append(torch.tensor(W, dtype=torch.float32))
            self.biases.append(torch.tensor(b, dtype=torch.float32))
            self.gammas.append(torch.tensor(g, dtype=torch.float32))

        self.weights = nn.ParameterList(self.weights)
        self.biases = nn.ParameterList(self.biases)
        self.gammas = nn.ParameterList(self.gammas)

    def forward(self, spatial: List[torch.Tensor], time: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Perform a forward pass through the network.

        :param spatial: List of input spatial tensors.
        :param time: Input tensor representing time.
        :return: A dictionary with output names as keys and corresponding output tensors as values.
        """
        if len(spatial) == 1:
            x = spatial[0]
            H = torch.cat((x, time), 1)
        elif len(spatial) == 2:
            x, y = spatial
            H = torch.cat((x, y, time), 1)
        else:
            x, y, z = spatial
            H = torch.cat((x, y, z, time), 1)
        
        H = (H - self.X_mean) / self.X_std

        for i, (W, b, g) in enumerate(zip(self.weights, self.biases, self.gammas)):
            # weight normalization
            V = W / torch.norm(W, dim=0)
            # matrix multiplication
            H = torch.matmul(H, V)
            # add bias
            H = g * H + b
            # activation
            if i < self.num_layers - 2:
                H = H * self.sigmoid(H)
        
        outputs_dict = {name: H[:, i : i + 1] for i, name in enumerate(self.output_names)}

        return outputs_dict
    


class ParallelNet(nn.Module): # rho, j and epsilon Network

    output_names: List[str]

    def __init__(self, layers1, layers2, lb, ub, output_names, act_function1: str = "sin", act_function2: str = "sin") -> None:

        super().__init__()


        self.model1 = self.initialize_net(layers1, act_function1)
        self.model2 = self.initialize_net(layers2, act_function2)
        self.register_buffer("lb", torch.tensor(lb, dtype=torch.float32, requires_grad=False))
        self.register_buffer("ub", torch.tensor(ub, dtype=torch.float32, requires_grad=False))
        self.output_names = output_names

    def initialize_net(self, layers: List, act_function: str):    
        """Initialize the layers of the neural network.

        :param layers: The list indicating number of neurons in each layer.
        :act_function: Tha activation function to use
        :return: The initialized neural network.
        """

        initializer = nn.init.xavier_uniform_
        net = nn.Sequential()

        input_layer = nn.Linear(layers[0], layers[1])
        initializer(input_layer.weight)

        net.add_module("input", input_layer)
        if act_function == "sin":
            net.add_module("activation_1", Sin())
        elif act_function == "sigmoid":
            net.add_module("activation_1", nn.Sigmoid())
        else:
            net.add_module("activation_1", nn.Tanh())
        

        for i in range(1, len(layers) - 2):
            hidden_layer = nn.Linear(layers[i], layers[i + 1])
            initializer(hidden_layer.weight)
            net.add_module(f"hidden_{i+1}", hidden_layer)
            if act_function == "sin":
                net.add_module(f"activation_{i+1}", Sin())
            elif act_function == "sigmoid":
                 net.add_module(f"activation_{i+1}", nn.Sigmoid()) 
            else:
                net.add_module(f"activation_{i+1}", nn.Tanh())


        output_layer = nn.Linear(layers[-2], layers[-1])
        initializer(output_layer.weight)
        net.add_module("output", output_layer)
        return net
    

    def forward(self, spatial: List[torch.Tensor], time: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Perform a single forward pass through the network.

    :param spatial: List of input spatial tensors.
    :param time: Input tensor representing time.
    :return: A tensor of solutions.
    """
        if len(spatial) == 1:
            x = spatial[0]
            z1 = torch.cat((x, time), 1)
            z2 = x
        elif len(spatial) == 2:
            x, y = spatial
            z1 = torch.cat((x, y, time), 1)
            z2 = torch.cat((x, y), 1)
        else:
            x, y, z = spatial
            z1 = torch.cat((x, y, z, time), 1)
            z2 = torch.cat((x, y, z), 1)
        z1 = 2.0 * (z1 - self.lb) / (self.ub - self.lb) - 1.0 
        z2 = 2.0 * (z2 - self.lb[0]) / (self.ub[0] - self.lb[0]) - 1.0
        z1 = self.model1(z1)
        z2 = torch.exp(self.model2(z2)) # enforcing positivity
        z = torch.cat((z1, z2), 1)
        outputs_dict = {name: z[:, i : i + 1] for i, name in enumerate(self.output_names)}
        return outputs_dict



if __name__ == "__main__":
   # _ = FCN()
   # _ = NetHFM()
    test = ParallelNet([2, 2, 2, 2], [1, 3, 5, 1], -1, 1, ['rho', 'j', 'eps'])
    print(test.model1)
    print(test.model2)
    print(test([torch.ones(1,1)], torch.ones(1,1)))
