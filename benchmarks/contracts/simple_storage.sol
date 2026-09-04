pragma solidity ^0.8.0;
contract SimpleStorage { uint256 private value; function set(uint256 v) external { value = v; } function get() external view returns (uint256) { return value; } }
