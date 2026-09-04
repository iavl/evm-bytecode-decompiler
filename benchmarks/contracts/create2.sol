pragma solidity ^0.8.0;
contract Create2Fixture { function deploy(bytes memory init, bytes32 salt) external returns (address deployed) { assembly { deployed := create2(0, add(init, 0x20), mload(init), salt) } } }
