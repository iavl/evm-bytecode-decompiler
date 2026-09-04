pragma solidity ^0.8.0;
contract ERC721Fixture { mapping(uint256 => address) public ownerOf; event Transfer(address indexed from, address indexed to, uint256 indexed id); function mint(uint256 id) external { ownerOf[id] = msg.sender; emit Transfer(address(0), msg.sender, id); } }
